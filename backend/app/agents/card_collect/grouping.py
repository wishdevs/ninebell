"""그룹 판단 계획 — 행 단위 AI 판단을 (가맹점×시간슬롯) 그룹 대표 판단으로 줄인다(순수 함수).

배경(사용자 확정 2026-07-31): 법인카드 한 달 내역(~340행)의 실제 판단 단위는 행이 아니라
(가맹점 × 시간슬롯) 그룹(~65개)이다 — 같은 가맹점·같은 시간대의 반복 결제는 분류가 같다.
전 행을 AI 로 보내는 대신 이 모듈이 '누구를 AI 로 보내고 누구에게 전파할지'를 계획한다:

  · learned 결정적 행(Tier 1, 호출부가 skip_ai 로 전달)은 AI 에서 제외 — 최종 선택에서
    AI 를 이기므로 보낼 이유가 없다(토큰·지연 낭비).
  · 남은 행은 그룹 **대표 1행**(금액 중앙값 근접)만 AI 로 보내고 결과를 그룹 전원에 전파한다.
  · 단, 그룹 금액대를 크게 벗어난 행(예: 맘스터치 저녁 15만원 — 회식/접대 가능성)은 전파에서
    빼고 **개별** AI 판단으로 승격한다. learned 결정적 적용도 우회한다(반복 확정은 평소
    금액대의 근거일 뿐, 이탈 결제의 근거가 아니다).
  · 승인취소 행은 같은 승인번호(APRVL_NO)의 원거래 최종 선택을 미러링한다(판단 불필요).
    APRVL_NO 는 승인/취소 쌍이 같은 번호다(js.py 프로브 실측) — 가맹점까지 대조해 오매칭을 막는다.

이 모듈은 브라우저·DB·LLM 을 건드리지 않는다(전부 순수 함수 — 단위 테스트 대상).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from app.services.card_learning import norm_merchant

from . import meal_time

# 금액 이탈 판정 — 그룹 표본이 이만큼 모여야 중앙값을 신뢰한다(2행뿐이면 근거 부족 → 판정 안 함).
OUTLIER_MIN_GROUP = 3
# 그룹 중앙값의 이 배수를 넘으면 이탈 후보. 야근식대는 여러 명 결제(2~5인분)가 정상 범위라
# 2배로는 오탐한다(실측: GS25 석식 중앙값 1만 vs 정상 팀 결제 2만).
OUTLIER_MULTIPLIER = 3.0
# 절대 하한 — 배수를 넘어도 이 금액 이하면 이탈로 보지 않는다(9,000원 vs 2,500원 같은
# 소액 편차는 성격이 같다). 사용자 기준(2026-07-31): 저녁식대는 여러 명 결제까지 ~5만원.
OUTLIER_FLOOR_WON = 50_000

# 시각 미상 표기 — 카드사가 승인 시각을 안 넘겨준 것(00:00:00, 사용자 확정 2026-07-29).
# 이를 조식 슬롯으로 묶으면 하나카드 00:00 행들이 엉뚱한 그룹이 된다 → 별도 슬롯.
_UNKNOWN_SLOT = "?"
_ZERO_TIME_RE = re.compile(r"^\s*00\s*:\s*00")


@dataclass(frozen=True)
class GroupPlan:
    """prefill 이 소비하는 판단 계획(전부 0-based 행 인덱스).

    ai_rows: AI 로 보낼 행 — 그룹 대표 + 금액 이탈(개별) 행. 정렬 보장.
    propagate: 전파 대상 행 → 그 그룹 대표 행(추천 결과를 복사받는다).
    outliers: 금액 이탈 행 — learned 결정적 적용 우회 + 개별 AI 판단.
    mirrors: 승인취소 행 → 원거래 행(최종 선택을 그대로 복사).
    """

    ai_rows: list[int] = field(default_factory=list)
    propagate: dict[int, int] = field(default_factory=dict)
    outliers: frozenset[int] = frozenset()
    mirrors: dict[int, int] = field(default_factory=dict)


def parse_amount(value: object) -> int | None:
    """TRAN_AMT('99,950'·'-13,600' 등)를 정수 원으로. 못 읽으면 None(판정에서 제외)."""
    s = str(value or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def is_cancel(row: dict) -> bool:
    """승인취소 행 여부 — APRVL_YN 라벨('승인취소') 우선, 보조로 음수 금액."""
    yn = str(row.get("APRVL_YN") or "")
    if "취소" in yn:
        return True
    amt = parse_amount(row.get("TRAN_AMT"))
    return amt is not None and amt < 0


def group_slot(time_str: str | None) -> str:
    """그룹 키용 시간 슬롯 — 조식/중식/석식 또는 '?'(시각 미상·판독 불가).

    00:00 표기는 자정 결제가 아니라 시각 미전달이므로 별도 슬롯으로 묶는다.
    """
    s = str(time_str or "")
    if not s or _ZERO_TIME_RE.match(s):
        return _UNKNOWN_SLOT
    return meal_time.slot_for_time(s) or _UNKNOWN_SLOT


def group_key(row: dict) -> tuple[str, str]:
    """(정규화 가맹점, 시간 슬롯) — 같은 가맹점이라도 점심/저녁은 분류가 갈리므로 슬롯을 나눈다
    (실측: 김치도가 점심=중식 / 저녁=야근식대)."""
    return (norm_merchant(row.get("TRAN_NM")), group_slot(row.get("TRAN_TM")))


def match_cancel_pairs(rows_list: list[dict]) -> dict[int, int]:
    """승인취소 행 → 원거래 행 매칭. 키는 (APRVL_NO, 정규화 가맹점) — 승인/취소 쌍이 같은
    승인번호를 쓴다. APRVL_NO 가 없으면 (가맹점, |금액|) 폴백. 원거래를 못 찾으면 매칭하지
    않는다(일반 파이프라인으로 흘려 보낸다 — 임의 추측 금지)."""
    originals_by_no: dict[tuple[str, str], list[int]] = {}
    originals_by_amt: dict[tuple[str, int], list[int]] = {}
    for idx, r in enumerate(rows_list):
        if is_cancel(r):
            continue
        merchant = norm_merchant(r.get("TRAN_NM"))
        no = str(r.get("APRVL_NO") or "").strip()
        if no:
            originals_by_no.setdefault((no, merchant), []).append(idx)
        amt = parse_amount(r.get("TRAN_AMT"))
        if amt is not None and amt > 0:
            originals_by_amt.setdefault((merchant, amt), []).append(idx)

    mirrors: dict[int, int] = {}
    used: set[int] = set()

    def _take(cands: list[int] | None) -> int | None:
        for c in cands or []:
            if c not in used:
                return c
        return None

    for idx, r in enumerate(rows_list):
        if not is_cancel(r):
            continue
        merchant = norm_merchant(r.get("TRAN_NM"))
        no = str(r.get("APRVL_NO") or "").strip()
        hit = _take(originals_by_no.get((no, merchant))) if no else None
        if hit is None:
            amt = parse_amount(r.get("TRAN_AMT"))
            if amt is not None and amt < 0:
                hit = _take(originals_by_amt.get((merchant, -amt)))
        if hit is not None:
            mirrors[idx] = hit
            used.add(hit)
    return mirrors


def _group_outliers(member_idxs: list[int], rows_list: list[dict]) -> set[int]:
    """그룹 내 금액 이탈 행 — 표본 OUTLIER_MIN_GROUP 미만이면 판정하지 않는다."""
    amounts = {
        i: a
        for i in member_idxs
        if (a := parse_amount(rows_list[i].get("TRAN_AMT"))) is not None and a > 0
    }
    if len(amounts) < OUTLIER_MIN_GROUP:
        return set()
    cut = max(OUTLIER_MULTIPLIER * median(amounts.values()), OUTLIER_FLOOR_WON)
    return {i for i, a in amounts.items() if a > cut}


def _pick_representative(member_idxs: list[int], rows_list: list[dict]) -> int:
    """대표 행 — 그룹 금액 중앙값에 가장 가까운 행(가장 '전형적인' 결제). 금액을 못 읽으면 첫 행."""
    amounts = {
        i: a
        for i in member_idxs
        if (a := parse_amount(rows_list[i].get("TRAN_AMT"))) is not None
    }
    if not amounts:
        return member_idxs[0]
    mid = median(amounts.values())
    return min(amounts, key=lambda i: (abs(amounts[i] - mid), i))


def plan_groups(rows_list: list[dict], skip_ai: set[int] | frozenset[int] = frozenset()) -> GroupPlan:
    """판단 계획 수립 — skip_ai 는 learned 결정적 행(AI 불필요, 단 금액 이탈이면 개별 AI 승격).

    수순: 취소 미러 매칭 → (가맹점×슬롯) 그룹핑(미러 행 제외) → 그룹별 이탈 판정 →
    그룹 대표 선정(비-learned·비-이탈 행 중) → AI 대상 = 대표 + 이탈 행.
    """
    mirrors = match_cancel_pairs(rows_list)
    groups: dict[tuple[str, str], list[int]] = {}
    for idx, r in enumerate(rows_list):
        if idx in mirrors:
            continue  # 취소 미러 행은 판단하지 않는다(원거래 복사).
        key = group_key(r)
        if not key[0]:
            key = (f"__무명{idx}", key[1])  # 가맹점명 없는 행은 서로 묶지 않는다(오전파 방지).
        groups.setdefault(key, []).append(idx)

    ai_rows: list[int] = []
    propagate: dict[int, int] = {}
    outliers: set[int] = set()
    for members in groups.values():
        outs = _group_outliers(members, rows_list)
        outliers |= outs
        # 이탈 행은 각자 개별 AI(전파 없음). learned 여부와 무관 — 반복 확정은 평소 금액대의
        # 근거일 뿐이라 이탈 결제엔 쓰지 않는다.
        ai_rows.extend(outs)
        normal = [i for i in members if i not in outs and i not in skip_ai]
        if not normal:
            continue  # 전원 learned/이탈 — 그룹 판단 불필요.
        rep = _pick_representative(normal, rows_list)
        ai_rows.append(rep)
        for m in normal:
            if m != rep:
                propagate[m] = rep
    return GroupPlan(
        ai_rows=sorted(ai_rows),
        propagate=propagate,
        outliers=frozenset(outliers),
        mirrors=mirrors,
    )
