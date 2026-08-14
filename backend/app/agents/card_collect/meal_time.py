"""식대 계정 시간대 교정 — 거래시각으로 조식/중식/석식을 최종 보정한다(순수 함수).

⚠ 왜 후처리인가(2026-07-27 사용자 감사 46건):
  예산계정 확정 순서는 `learned(개인 확정) → AI → seed → dict → 기본지정` 이고,
  **learned 가 AI 를 우회한다**(prefill.py). 즉 점심에 한 번 '석식'으로 확정한 가맹점은
  이후 11시 결제도 계속 석식으로 굳는다 — AI 프롬프트에 거래시각을 넣어도 그 경로는 손댈 수
  없다. 그래서 **어느 경로로 정해졌든 마지막에 한 번** 시각과 대조해 형제 계정으로 바꾼다.

경계(사규 변경 2026-08-13 — **중식 폐지**):
  · ~11:00  조식
  · 11:00~  석식   ← 종전 중식 구간(11~15시)도 이제 석식으로 처리한다
  야식 계정은 ERP 카탈로그에 **없어**(실측: 2,321건 중 0건) 22시 이후도 석식으로 둔다.

⚠ 중식 폐지의 구현(2026-08-13): `slot_for_time` 은 더 이상 중식을 반환하지 않지만, 중식은
  `_SLOTS`(계정 판별)에 **그대로 남긴다** — 그래야 learned/AI/seed 가 고른 기존 '복리후생비-중식'
  계정이 시간대 계정으로 인식돼 이 교정에서 석식으로 바뀐다. 목록에서 빼면 '교정 대상 아님'이
  되어 중식이 그대로 저장된다(정반대 결과).

⚠ 교정 대상은 **이미 식대 시간대 계정인 행**뿐이다. 간식·회식·업무·음료 등은 시간대가 아니라
  성격 구분이라 건드리지 않는다(잘못 건드리면 정상 분류를 깬다).
"""

from __future__ import annotations

import re

from .nodes.catalog import _acct_norm

BREAKFAST = "조식"
LUNCH = "중식"
DINNER = "석식"

# 경계(시). 조식 < DINNER_FROM_HOUR ≤ 석식. (중식 구간은 2026-08-13 사규 변경으로 폐지)
DINNER_FROM_HOUR = 11

# 시간대 계열 슬롯 — **중식 포함**. 시각→중식 매핑은 폐지됐지만, 기존 중식 계정을 교정 대상으로
# 인식하려면 여기 남아 있어야 한다(모듈 docstring 참조).
_SLOTS = (BREAKFAST, LUNCH, DINNER)
# 계정명에 이 문자열이 들어가면 그 슬롯의 식대 계정으로 본다(정규화 후 부분일치).
# ⚠ 실제 표기 예: '(판)복리후생비-석식 (연장근무 식대)', '(판) 복리후생비_조식(IMP)' —
#   괄호·공백·언더스코어가 섞여 정확일치가 불가능하므로 _acct_norm 정규화 후 부분일치한다.
_MEAL_FAMILY = "복리후생비"
_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*:\s*(\d{2})")


def slot_for_time(time_str: str | None) -> str | None:
    """거래시각('HH:MM:SS')이 속한 식사 슬롯. 시각을 못 읽으면 None(교정하지 않음).

    ⚠ 2026-08-13 사규 변경으로 **중식은 반환하지 않는다** — 11시 이후는 전부 석식이다.
    """
    m = _TIME_RE.match(str(time_str or ""))
    if not m:
        return None
    hour = int(m.group(1))
    if hour < 0 or hour > 23:
        return None
    return BREAKFAST if hour < DINNER_FROM_HOUR else DINNER


def account_slot(bgacct_nm: str | None) -> str | None:
    """예산계정명이 식대 **시간대 계정**이면 그 슬롯, 아니면 None(간식·회식·업무 등 제외)."""
    norm = _acct_norm(bgacct_nm)
    if not norm or _acct_norm(_MEAL_FAMILY) not in norm:
        return None
    for slot in _SLOTS:
        if slot in norm:
            return slot
    return None


def _prefix(bgacct_nm: str | None) -> str:
    """'(판)'/'(제)' 접두 — 치환 시 같은 접두를 유지해야 한다(판/제는 비용구분이 다르다)."""
    text = str(bgacct_nm or "")
    for p in ("(판)", "(제)"):
        if text.replace(" ", "").startswith(p):
            return p
    return ""


def find_sibling(candidates: list[dict], current_nm: str | None, target_slot: str) -> dict | None:
    """같은 접두·같은 복리후생비 계열에서 target_slot 계정 후보를 찾는다(없으면 None).

    ⚠ 같은 슬롯 계정이 여럿이면(예: '(판)복리후생비-조식' vs '(판) 복리후생비_조식(IMP)')
      **표기가 단순한 쪽**을 고른다 — IMP 같은 변형은 용도가 달라 임의로 쓰면 안 된다.
    """
    want_prefix = _prefix(current_nm)
    matches = [
        c
        for c in candidates
        if account_slot(c.get("bgacctNm")) == target_slot and _prefix(c.get("bgacctNm")) == want_prefix
    ]
    if not matches:
        return None
    return min(matches, key=lambda c: len(str(c.get("bgacctNm") or "")))


def correct_budget(
    budget: dict | None, time_str: str | None, candidates: list[dict]
) -> tuple[dict | None, str | None]:
    """식대 시간대 계정을 거래시각에 맞게 보정한다.

    반환 (보정된 후보 | None, 사유 | None). None 이면 교정 대상이 아니거나 형제 계정이 없어
    **원본을 그대로 둔다**(임의 변경 금지 — 갈 곳이 없으면 건드리지 않는 편이 안전하다).
    """
    if not budget:
        return None, None
    current_nm = budget.get("bgacctNm")
    current_slot = account_slot(current_nm)
    if current_slot is None:
        return None, None  # 시간대 계정이 아님(간식·회식·업무 등) — 교정 대상 아님.
    want = slot_for_time(time_str)
    if want is None or want == current_slot:
        return None, None
    sibling = find_sibling(candidates, current_nm, want)
    if not sibling:
        return None, None  # 예: 야식 시간대인데 야식 계정이 없다 → 그대로 둔다.
    return sibling, f"{current_slot}→{want}(거래시각 {time_str})"
