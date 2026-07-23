"""카드 개입 학습 — 가맹점→선택 저장(upsert)·조회(retrieve)·유사매칭.

card-collect 개입에서 확정한 선택을 가맹점 단위로 누적하고, 다음 런에서 **이번 런에 등장한
가맹점만** 조회해 AI 추천 힌트/결정적 프리필로 재사용한다. 프롬프트에 전 이력을 넣지 않으므로
(검색-후-주입) 학습분이 아무리 커도 프롬프트 크기는 런의 행 수에 비례한다.

DB 세션은 라우터 밖(세션 펌프)에서도 쓰이므로 store 처럼 get_sessionmaker() 로 자체 세션을 연다.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import (
    CardAiNote,
    CardLearnedNote,
    CardLearnedSelection,
    CardSeedNote,
    CardSeedSelection,
)

logger = logging.getLogger("app.services.card_learning")

# 결정적 적용(Tier 1) 판정: 같은 가맹점을 이 횟수 이상 동일 확정했으면 AI 없이 그대로 프리필.
LEARNED_APPLY_MIN_COUNT = 3

# seed 적요(CardSeedNote)를 확정으로 채택할 최소 dominance(= 그 가맹점×계정 조합에서 최빈 적요의
# 최근성 가중 비율). 미만이면 그 조합은 실제 적요가 여러 갈래라는 뜻이라 최빈 하나를 확정하지 않고
# AI tier 로 넘긴다 — 실측(2026-07-23): 아고다는 '여비교통비-해외출장' 하나에 항공·숙박이 섞이는데
# 최빈이 '해외출장 교통비'라 숙박 결제에도 교통비가 박혔다. 과반(0.5)을 확정의 하한으로 둔다.
SEED_NOTE_MIN_DOMINANCE = 0.5


def norm_merchant(name: str | None) -> str:
    """가맹점명 매칭 키 — 공백·괄호표기·부호를 흡수해 '네이버파이낸셜㈜'↔'네이버파이낸셜(주)' 등을 묶는다."""
    s = str(name or "")
    s = s.replace("㈜", "주식회사").replace("(주)", "주식회사").replace("（주）", "주식회사")
    s = re.sub(r"[\s()\[\]{}·・,./\-_'\"]+", "", s)
    return s.lower()


# ── 적요 PII 정리 — 차량번호·사람이름 괄호·개인 물품 상세 제거(사용자 확정 2026-07-22) ──────
# R1 차량번호: '157하5208' 류. 괄호 덩어리는 [^)]* 가 여는 괄호도 삼켜 중첩/미닫힘
# ("(임원실 159호4288 (팰리세이드)") 케이스까지 한 번에 제거된다.
# 가운데 글자는 **실제 번호판 한글 명시 목록** — [가-힣] 범위는 '만'(10만5000)·'년'(2022년1234)
# 을 포함해 금액/연도를 오검출하므로 금지(적대 리뷰 2026-07-22 확정).
_PLATE_KO = "[가나다라마거너더러머고노도로모구누두루무버서어저보소오조부수우주바사아자하허호배]"
_PLATE_RE = re.compile(rf"\d{{2,3}}{_PLATE_KO}\d{{4}}")
_PLATE_PAREN_RE = re.compile(rf"\([^)]*\d{{2,3}}{_PLATE_KO}\d{{4}}[^)]*\)?")
# R2 사람이름 괄호: (이대훈)·(장일환,손용선)·(장일환 외 2명) 류 — 콤마/·// 나열 + '외 N명' 꼬리까지
# 잡는다. (법인카드)/(판매) 등 관용 괄호는 negative lookahead 로 보존(_TRIP_NAME_RE 와 같은
# 관용어 방식, 목록은 사용자 확정 10종). ⚠ '(본부 직원 전체 6명)' 같은 콤마 없는 공백 나열은
# 매치되지 않아야 한다(보존 — 테스트 감시).
_NAME_PAREN_RE = re.compile(
    r"\((?!법인|신용|불공|판매|제품|제조|판관|기타|공통|해외)"
    r"[가-힣]{2,4}(?:\s*[,·/]\s*[가-힣]{2,4})*(?:\s*외\s*\d+\s*명)?\)"
)
# R3 개인 물품 상세: '소모품 구입 (라센트라 크리넥스)' → '소모품 구입' 절단.
# 관용 괄호는 lookahead 로 게이트 — '소모품 구입 (법인카드)-판매' 는 원문 보존(적대 리뷰 확정).
_SUPPLY_PREFIX_RE = re.compile(r"^(소모품 ?구입)\s*\((?!법인|신용|불공|판매|제품|제조|판관|기타|공통|해외)")


def sanitize_note(note: str | None) -> str | None:
    """적요의 개인정보 잔재(차량번호·사람이름 괄호·개인 물품 상세) 제거 — 멱등.

    규칙 출처: 2026-07-22 사용자 지시 — DB 전수 실측 기반 확정(card_seed_notes 차량번호 203건·
    이름 13건·소모품 괄호 2건, learned/ai 0건이나 3테이블 모두 방어 적용). 규칙:
      R1 차량번호 — 괄호 덩어리 통째 + 괄호 밖 맨몸 제거, 적용된 행에 한해 '차랑유류비' 오탈자 정정.
      R2 사람이름 괄호 — (이대훈) 류 제거, (법인카드)/(판매) 등 관용 괄호는 보존
         (strip_division/apply_cost_suffix 가 의존하므로 회귀 금지).
      R3 '소모품 구입 (…)' — 개인 물품 상세를 떼고 '소모품 구입'으로 절단.
    후처리: 연속 공백 1개·양끝 공백·고아 괄호/따옴표 잔해 정리, 빈 결과는 None
    (NULL — 추천 사다리의 note.isnot(None) 필터가 자연 제외). 정리본에 재적용해도 불변(멱등).
    ⚠ 원본 동기화: alembic **0023_resanitize_card_note_pii** 가 이 규칙의 최신 복제본이다 —
    규칙 변경 시 양쪽(여기 + 0023) 동기화. 0022 는 구규칙으로 이미 적용된 역사라 수정하지 않는다
    (패리티 감시 대상은 0023, tests/test_card_note_sanitize.py).
    """
    if note is None:
        return None
    s = str(note)
    # R1 — 차량번호: 괄호 덩어리 → 괄호 밖 맨몸 순으로 제거.
    r1 = _PLATE_PAREN_RE.sub(" ", s)
    r1 = _PLATE_RE.sub(" ", r1)
    if r1 != s:
        r1 = r1.replace("차랑유류비", "차량유류비")  # 오탈자 정정 — R1 적용된 행에 한해.
    s = r1
    # R2 — 사람이름 괄호 제거(관용 괄호는 lookahead 로 보존).
    s = _NAME_PAREN_RE.sub(" ", s)
    # R3 — '소모품 구입 (…)' 개인 물품 상세 절단.
    m = _SUPPLY_PREFIX_RE.match(s.strip())
    if m:
        s = m.group(1)
    # 후처리 — 빈 괄호쌍·고아 괄호·연속 공백·양끝 고아 따옴표 정리.
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\s*\(+\s*$", "", s)  # 끝에 남은 여는 괄호 고아
    s = re.sub(r"^\s*\)+\s*", "", s)  # 앞에 남은 닫는 괄호 고아
    s = re.sub(r"\s+", " ", s).strip()
    for q in ('"', "'"):
        if s.count(q) == 1 and (s.startswith(q) or s.endswith(q)):
            s = s.strip(q).strip()
    return s or None


# ── 적요 정규화 — 사람이름 제외 + 판매/제조 구분 동적화(사용자 확정 2026-07-20) ─────────────
# 접속자 소속 비용구분 → 적요 끝에 붙일 구분 접미사. 판관비=판매, 제조원가=제조.
COST_TYPE_SUFFIX: dict[str, str] = {"판관비": "판매", "제조원가": "제조"}

# 원본 적요에 붙어 있던 판/제 구분(제거 대상) — 끝의 대시(-판매/-제품/-제조/-판관) 또는 괄호((판매)/…).
# '제품'은 제조원가 쪽 원본 표기. 끝 1개만 떼어 base 로 되돌린다.
_TRAILING_DIVISION_RE = re.compile(r"\s*(?:-\s*(?:판매|제품|제조|판관)|\((?:판매|제품|제조|판관)\))\s*$")
# 사람이름 적요(추천 금지): (A) 콤마로 이어진 2인 이상 이름 나열이 앞에, (B) '출장' 적요 괄호 안 이름.
# '(법인카드)'·'(불공)' 등 관용 괄호는 negative lookahead 로 제외해 오검출(직원 야근식대 등)을 막는다.
_NAME_LIST_RE = re.compile(r"^[가-힣]{2,4}(?:\s*,\s*[가-힣]{2,4})+")
_TRIP_NAME_RE = re.compile(
    r"출장.*\((?!법인|불공|판매|제품|제조|판관)[가-힣]{2,4}(?:\s*,\s*[가-힣]{2,4})*(?:\s*외\s*\d+명)?\)"
)


def is_person_name_note(note: str | None) -> bool:
    """적요에 사람이름이 들어가 그대로 추천하면 안 되는지. (A) '박건희, 이재혁 석식' 이름나열,
    (B) '중국출장 숙박(장일환)' 출장 괄호 이름. 관용 괄호((법인카드) 등)는 오검출 안 하도록 제외."""
    if not note:
        return False
    s = note.strip()
    return bool(_NAME_LIST_RE.match(s) or _TRIP_NAME_RE.search(s))


def strip_division(note: str) -> tuple[str, bool]:
    """적요 끝의 판/제 구분(-판매/-제품/(판매)…)을 떼고 (base, 원래_구분있었나) 반환. 없으면 (원문, False)."""
    m = _TRAILING_DIVISION_RE.search(note)
    if not m:
        return note.strip(), False
    return note[: m.start()].strip(), True


def apply_cost_suffix(note: str | None, cost_type: str | None) -> str | None:
    """추천/표시용 적요 정규화 — 판/제 구분을 떼고, **원래 구분이 있던 적요만** 접속자 비용구분
    (판관비→판매 / 제조원가→제조)으로 재부착. 구분이 원래 없던 적요는 그대로. cost_type 미상이면 base."""
    if note is None:
        return None
    base, had = strip_division(note)
    if not base:
        return None
    if had:
        suffix = COST_TYPE_SUFFIX.get((cost_type or "").strip())
        if suffix:
            return f"{base}-{suffix}"
    return base


def _uuid(owner: str | None) -> uuid.UUID | None:
    if not owner:
        return None
    try:
        return uuid.UUID(str(owner))
    except (ValueError, TypeError):
        return None


async def record_selections(owner: str | None, entries: list[dict]) -> int:
    """확정 선택을 (user, norm_merchant) upsert. entries={merchant, budget, project, note}.

    같은 가맹점 재확정은 count++ + 스냅샷 갱신(최신 선택 우선). 반환 upsert 건수. owner 없거나
    (스크립트/익명) 예외면 조용히 0(학습은 부가기능 — 런을 죽이지 않는다).
    """
    uid = _uuid(owner)
    if uid is None or not entries:
        return 0
    # ⚠ 같은 런에 같은 가맹점이 2건 이상이면 (user, norm_merchant) 유니크가 걸려 커밋 전체가
    # 롤백돼 아무것도 저장 안 되던 버그(2026-07-05 실측: '네이버파이낸셜' 중복). 배치 내 중복
    # 가맹점을 **최신 선택 우선으로 1건으로 접는다**(같은 결정의 반복이므로 런당 1회 확정).
    collapsed: dict[str, dict] = {}
    for e in entries:
        key = norm_merchant((e.get("merchant") or "").strip())
        if key:
            collapsed[key] = e
    if not collapsed:
        return 0
    now = datetime.now(UTC)
    n = 0
    try:
        async with get_sessionmaker()() as s:
            for key, e in collapsed.items():
                merchant = (e.get("merchant") or "").strip()
                row = (
                    await s.execute(
                        select(CardLearnedSelection).where(
                            CardLearnedSelection.user_id == uid,
                            CardLearnedSelection.norm_merchant == key,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    s.add(
                        CardLearnedSelection(
                            user_id=uid,
                            norm_merchant=key,
                            merchant=merchant,
                            budget=e.get("budget") or None,
                            project=e.get("project") or None,
                            note=(e.get("note") or "").strip() or None,
                            count=1,
                            last_used_at=now,
                        )
                    )
                else:
                    row.merchant = merchant or row.merchant
                    row.budget = e.get("budget") or row.budget
                    row.project = e.get("project") or row.project
                    if (e.get("note") or "").strip():
                        row.note = e["note"].strip()
                    row.count = (row.count or 0) + 1
                    row.last_used_at = now
                n += 1
            await s.commit()
    except Exception:  # noqa: BLE001 — 학습 실패가 런/제출을 깨선 안 된다.
        logger.exception("card learning record_selections failed")
        return 0
    return n


async def record_account_notes(owner: str | None, entries: list[dict]) -> int:
    """확정행의 (계정 × 적요)를 (user, norm_merchant, acct_code) 로 upsert.

    entries={merchant, acct_code, acct_name, note}. 사람이 예산단위(=계정)를 바꾸고 적요를 확정한
    행만 넘어온다(호출부가 noteEdited 게이트). 같은 (가맹점 × 계정) 재확정은 count++ + 최신 적요
    갱신. record_selections(가맹점 단위 예산 학습)와 **병행** — 이 함수는 계정별 적요만 담당한다.

    계정코드 없으면 skip(방어). owner 없거나 예외면 조용히 0(학습은 부가기능 — 런을 죽이지 않는다).
    """
    uid = _uuid(owner)
    if uid is None or not entries:
        return 0
    # ⚠ 같은 런에 같은 (가맹점 × 계정)이 2건 이상이면 유니크 위반으로 커밋 전체가 롤백된다
    # (record_selections 의 네이버 회귀와 동종). 배치 내 중복을 최신 선택 우선 1건으로 접는다.
    collapsed: dict[tuple[str, str], dict] = {}
    for e in entries:
        merchant = (e.get("merchant") or "").strip()
        key = norm_merchant(merchant)
        acct_code = (e.get("acct_code") or "").strip()
        if not key or not acct_code:
            continue
        collapsed[(key, acct_code)] = {**e, "merchant": merchant}
    if not collapsed:
        return 0
    now = datetime.now(UTC)
    n = 0
    try:
        async with get_sessionmaker()() as s:
            for (key, acct_code), e in collapsed.items():
                row = (
                    await s.execute(
                        select(CardLearnedNote).where(
                            CardLearnedNote.user_id == uid,
                            CardLearnedNote.norm_merchant == key,
                            CardLearnedNote.acct_code == acct_code,
                        )
                    )
                ).scalar_one_or_none()
                # 기록 경로 정리 — 확정 적요에 남은 PII(차량번호·이름 괄호)를 들어올 때 걷어낸다.
                note = sanitize_note(e.get("note"))
                acct_name = (e.get("acct_name") or "").strip() or None
                if row is None:
                    s.add(
                        CardLearnedNote(
                            user_id=uid,
                            norm_merchant=key,
                            merchant=e["merchant"],
                            acct_code=acct_code,
                            acct_name=acct_name,
                            note=note,
                            count=1,
                            last_used_at=now,
                        )
                    )
                else:
                    row.merchant = e["merchant"] or row.merchant
                    if acct_name:
                        row.acct_name = acct_name
                    if note:
                        row.note = note
                    row.count = (row.count or 0) + 1
                    row.last_used_at = now
                n += 1
            await s.commit()
    except Exception:  # noqa: BLE001 — 학습 실패가 런/제출을 깨선 안 된다.
        logger.exception("card learning record_account_notes failed")
        return 0
    return n


async def retrieve_for_merchants(owner: str | None, merchants: list[str]) -> dict[str, dict]:
    """이번 런 가맹점들에 대한 학습분만 조회 → {norm_merchant: {merchant,budget,project,note,count}}.

    프롬프트 주입/결정적 프리필의 소스. owner 의 학습 전체가 아니라 **요청 가맹점 키에 해당하는
    행만** 로드하므로 주입량이 런 크기에 비례(전 이력 무관). 정확 키 매칭(정규화)만 — 유사매칭은
    호출부에서 norm 키 부분일치로 보강 가능.
    """
    uid = _uuid(owner)
    if uid is None or not merchants:
        return {}
    keys = {norm_merchant(m) for m in merchants if norm_merchant(m)}
    if not keys:
        return {}
    try:
        async with get_sessionmaker()() as s:
            rows = (
                await s.execute(
                    select(CardLearnedSelection).where(
                        CardLearnedSelection.user_id == uid,
                        CardLearnedSelection.norm_merchant.in_(keys),
                    )
                )
            ).scalars().all()
    except Exception:  # noqa: BLE001
        logger.exception("card learning retrieve failed")
        return {}
    return {
        r.norm_merchant: {
            "merchant": r.merchant,
            "budget": r.budget,
            "project": r.project,
            "note": r.note,
            "count": r.count,
        }
        for r in rows
    }


async def retrieve_seed_for_merchants(merchants: list[str]) -> dict[str, dict]:
    """전사 기초자료(card_seed_selections)에서 이번 런 가맹점들만 조회 → {norm: {...}}.

    개인 학습(retrieve_for_merchants)이 없을 때의 **전사 폴백 tier**. user 무관 공용이며 조회는
    요청 가맹점 키로만 스코프(전 이력 무관, 프롬프트 크기는 런 크기에 비례). 반환 각 값:
    {merchant, acct_code, acct_name, note, count, dominance}. 결정적 적용이 아니라 AI 힌트·
    개선된 폴백으로만 쓴다(키워드 매칭 + 비개인 데이터 → 최종값 아님, AI가 맥락으로 판단)."""
    keys = {norm_merchant(m) for m in merchants if norm_merchant(m)}
    if not keys:
        return {}
    try:
        async with get_sessionmaker()() as s:
            rows = (
                await s.execute(
                    select(CardSeedSelection).where(CardSeedSelection.norm_merchant.in_(keys))
                )
            ).scalars().all()
    except Exception:  # noqa: BLE001 — 조회 실패가 런을 죽여선 안 된다(부가기능).
        logger.exception("card seed retrieve failed")
        return {}
    return {
        r.norm_merchant: {
            "merchant": r.merchant,
            "acct_code": r.acct_code,
            "acct_name": r.acct_name,
            "note": r.note,
            "count": r.count,
            "dominance": r.dominance,
        }
        for r in rows
    }


# ── AI tier: learned/seed 미스 조합의 계정 맞춤 적요 생성(전사 공유 캐시) ──────────────
_AI_NOTE_SYSTEM = (
    "너는 법인카드 지출 적요(비용 설명 문구)를 작성하는 회계 보조다. 주어진 예산계정(용도)과 "
    "가맹점명에 맞는 간결한 한국어 적요 한 줄을 만든다.\n"
    "규칙:\n"
    "1) 지금 고른 예산계정의 용도를 반드시 반영한다(가맹점의 과거 통계가 아니라 이 계정이 기준).\n"
    "2) 회사 관례 표기 '{용도}(법인카드)' 형태를 따른다.\n"
    "3) 25자 이내. 따옴표·설명·부연·줄바꿈 없이 적요 문구만 출력한다.\n"
    "4) 가맹점 성격이 계정과 자연스럽게 맞으면 녹이되, 억지로 넣지 않는다.\n"
    "5) 지출 성격을 좁히는 것은 근거가 있을 때만 한다. 같은 가맹점·계정에서 여러 성격이 가능하면"
    "(예: 여행 예약 사이트는 항공권일 수도 숙박일 수도 있다) 하나로 단정하지 말고 계정 수준의"
    " 포괄 표현을 쓴다. 틀린 구체 표현보다 맞는 포괄 표현이 낫다."
)


async def _ai_note_cached(session: AsyncSession, norm: str, acct: str) -> str | None:
    """(norm_merchant, acct_code) AI 캐시 조회(전사 공유). 없으면 None."""
    row = (
        (
            await session.execute(
                select(CardAiNote.note)
                .where(CardAiNote.norm_merchant == norm, CardAiNote.acct_code == acct)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return row.strip() if row and row.strip() else None


async def _ai_note_generate(merchant: str, acct_name: str) -> tuple[str, str] | None:
    """(가맹점, 계정이름) → LLM 계정 맞춤 적요(활성 프로바이더). 반환 (note, model).

    키 없음/네트워크·모델 오류/빈 응답이면 None → 호출자가 category·heuristic 로 폴백한다.
    """
    settings = get_settings()
    # 지연 import 로 app.agents 순환참조 회피(heuristic tier 와 동일 규율).
    from app.agents.common.llm import generate_text, llm_model_name, llm_ready

    if not llm_ready(settings):  # gemini 키 없으면 조용히 스킵(결정적 폴백). etribe 는 무인증.
        return None

    model = llm_model_name(settings)  # 캐시(CardAiNote.model) 기록용 — 활성 프로바이더 모델명.
    user = f"예산계정: {acct_name.strip()}\n가맹점: {merchant.strip()}\n적요:"
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            raw = await generate_text(
                http,
                system=_AI_NOTE_SYSTEM,
                user=user,
                temperature=0.2,
                max_output_tokens=128,
                thinking_budget=0,  # 적요 생성엔 사고 불필요 — 사고 토큰이 출력을 잠식하지 않게 끈다.
                settings=settings,
            )
    except Exception:  # noqa: BLE001 — LLM 실패가 추천을 죽여선 안 된다(폴백 존재).
        logger.warning("ai note generate failed (merchant=%r acct_name=%r)", merchant, acct_name)
        return None
    if not raw:
        return None
    note = raw.splitlines()[0].strip().strip("\"'`").removeprefix("적요:").strip()
    if not note:
        return None
    return note[:255], model


async def _ai_note_store(
    *, norm: str, merchant: str, acct: str, acct_name: str, note: str, model: str
) -> None:
    """생성 적요를 캐시에 저장 — 호출자 트랜잭션과 분리된 별도 세션으로. 실패는 조용히 무시.

    동시 요청이 같은 조합을 생성하면 유니크 경쟁이 날 수 있는데, 그건 캐시 실패로 보고 무시한다
    (다음 조회 때 둘 중 하나가 이미 있으므로 정상). 캐시 쓰기 실패가 응답을 막지 않게 한다.
    """
    # 기록 경로 정리 — 생성 적요에 PII 가 섞여도 캐시에 들어가지 않게(재오염 방지).
    clean = sanitize_note(note)
    if not clean:
        return  # 정리 후 빈 적요 — note 는 NOT NULL 캐시라 저장 자체를 건너뛴다(다음에 재생성).
    try:
        async with get_sessionmaker()() as s:
            s.add(
                CardAiNote(
                    norm_merchant=norm,
                    merchant=merchant,
                    acct_code=acct,
                    acct_name=acct_name,
                    note=clean,
                    model=model,
                )
            )
            await s.commit()
    except Exception:  # noqa: BLE001 — 유니크 경쟁/DB 오류 → 캐시 실패는 무시.
        logger.debug("ai note cache store skipped (merchant=%r acct=%r)", merchant, acct)


# suggest_note 의 tier 별 방어 규율: 각 tier 후보를 sanitize_note 로 정리해 **truthy 일 때만**
# 그 tier 로 반환하고, 정리 결과가 빈값(순수 PII)이면 다음 tier 로 폴스루한다
# (is_person_name_note skip 과 동일 패턴 — 미정리 서버에서도 사다리가 죽지 않는다).


async def suggest_note(
    session: AsyncSession,
    *,
    user_id: str | uuid.UUID | None,
    merchant: str,
    acct_code: str | None,
    acct_name: str | None = None,
    allow_ai: bool = False,
    ai_on_ambiguous_seed: bool = False,
    cost_type: str | None = None,
) -> dict:
    """(가맹점 × 계정) → 적요 리졸버 — learned>seed>[AI]>category>heuristic 사다리(첫 히트 반환).

    반환 {"note": str|None, "source": "learned"|"seed"|"ai"|"category"|"heuristic"|None}.
    계정(acct_code) 있으면 개인학습(CardLearnedNote, 가장 구체적) → 전사 seed(CardSeedNote,
    가맹점×계정) → (allow_ai + acct_name 있으면) AI 계정 맞춤 적요(CardAiNote 캐시 우선, 없으면
    Gemini 생성 후 캐시) → 그 계정의 최빈 적요(CardSeedNote 를 acct_code 로 GROUP BY) 순으로
    매칭하고, 못 찾으면 가맹점명 키워드 휴리스틱으로 폴백. 계정 없으면 계정 tier 를 스킵하고 휴리스틱만.

    AI tier 는 learned/seed 로 **확정할 수 없는** 조합에서만 돈다 — (a) 통계로 못 메우는
    "네이버파이낸셜 + 회의비" 같은 미학습 계정 조합, (b) seed 는 있지만 그 조합 안에서 적요가
    갈리는(dominance < SEED_NOTE_MIN_DOMINANCE) 저신뢰 조합. 계정 이름(acct_name)으로 계정 맞춤
    적요를 생성한다.

    AI opt-in 은 둘로 나뉜다. allow_ai=True 는 사람이 트리거하는 엔드포인트(GET /me/note-suggest)
    가 쓰고 (a)·(b) 모두 AI 를 태운다. ai_on_ambiguous_seed=True 는 배치(collect 초기 프리필)가
    쓰고 **(b) 저신뢰 seed 조합에만** AI 를 태운다 — 미학습 조합까지 배치에서 생성하면 카드 런마다
    LLM 호출이 늘어나므로, 배치는 '결정적으로 틀린 값이 박히는' 경우만 산다(캐시는 전사 공유라
    같은 조합의 재호출 비용은 0). AI 실패/키없음이면 조용히 category·heuristic 로 폴백한다.
    세션은 호출부(라우터 DbSession / 노드 자체 세션)가 주입한다.
    """
    norm = norm_merchant(merchant)
    acct = (acct_code or "").strip()

    if acct:
        uid = _uuid(user_id)
        # 1) learned — (user, norm, acct) 개인 학습(가장 구체적, 결정적).
        if uid is not None and norm:
            learned_note = (
                (
                    await session.execute(
                        select(CardLearnedNote.note)
                        .where(
                            CardLearnedNote.user_id == uid,
                            CardLearnedNote.norm_merchant == norm,
                            CardLearnedNote.acct_code == acct,
                        )
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            # 사람이름 적요는 건너뛰고 다음 티어(깨끗한 적요)로 폴백한다.
            if learned_note and learned_note.strip() and not is_person_name_note(learned_note):
                # 정리 결과가 빈값(순수 PII)이면 반환하지 않고 다음 tier 로 폴스루.
                clean = sanitize_note(apply_cost_suffix(learned_note, cost_type))
                if clean:
                    return {"note": clean, "source": "learned"}
        # 2) seed — (norm, acct) 전사 가맹점×계정 관례. 단 그 조합 안에서 적요가 갈리면
        #    (dominance < SEED_NOTE_MIN_DOMINANCE) 최빈 하나를 확정으로 쓰지 않고 흘려보낸다.
        ambiguous_seed = False
        if norm:
            seed_row = (
                await session.execute(
                    select(CardSeedNote.note, CardSeedNote.dominance)
                    .where(
                        CardSeedNote.norm_merchant == norm,
                        CardSeedNote.acct_code == acct,
                    )
                    .limit(1)
                )
            ).first()
            seed_note = seed_row[0] if seed_row else None
            seed_dom = float(seed_row[1] or 0.0) if seed_row else 0.0
            if seed_note and seed_note.strip() and not is_person_name_note(seed_note):
                if seed_dom < SEED_NOTE_MIN_DOMINANCE:
                    # 같은 가맹점×계정인데 실제 적요가 여러 갈래(항공·숙박이 섞이는 예약 사이트 등).
                    # 최빈값을 확정하면 틀린 구체 표현이 박히므로 AI tier 로 넘긴다.
                    ambiguous_seed = True
                else:
                    clean = sanitize_note(apply_cost_suffix(seed_note, cost_type))
                    if clean:
                        return {"note": clean, "source": "seed"}
        # 3) AI — learned/seed 에 (가맹점×계정) 실이력이 없거나(미학습), 있어도 적요가 갈려
        #    확정할 수 없는(ambiguous_seed) 조합. 계정 이름으로 계정 맞춤 적요를 생성한다
        #    (캐시 우선, 전사 공유). 엔드포인트는 allow_ai, 배치는 ai_on_ambiguous_seed 로 opt-in.
        acct_nm = (acct_name or "").strip()
        if (allow_ai or (ai_on_ambiguous_seed and ambiguous_seed)) and norm and acct_nm:
            cached = await _ai_note_cached(session, norm, acct)
            if cached:
                clean = sanitize_note(cached)
                if clean:
                    return {"note": clean, "source": "ai"}
            gen = await _ai_note_generate(merchant, acct_nm)
            if gen is not None:
                gen_note, gen_model = gen
                clean = sanitize_note(gen_note)
                if clean:  # 생성분이 순수 PII 면 캐시도 반환도 없이 다음 tier 로.
                    await _ai_note_store(
                        norm=norm,
                        merchant=merchant,
                        acct=acct,
                        acct_name=acct_nm,
                        note=gen_note,
                        model=gen_model,
                    )
                    return {"note": clean, "source": "ai"}
        # 4) category — 그 계정의 최빈 적요(count 합 최대). 사람이름 적요는 건너뛰고 상위 후보 중 첫
        #    깨끗한 것을 쓴다(쿼리타임 집계, 별도 테이블 없음).
        total = func.sum(CardSeedNote.count)
        cat_rows = (
            (
                await session.execute(
                    select(CardSeedNote.note)
                    .where(CardSeedNote.acct_code == acct, CardSeedNote.note.isnot(None))
                    .group_by(CardSeedNote.note)
                    .order_by(total.desc(), CardSeedNote.note.asc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        for cat_note in cat_rows:
            if cat_note and cat_note.strip() and not is_person_name_note(cat_note):
                clean = sanitize_note(apply_cost_suffix(cat_note, cost_type))
                if clean:
                    return {"note": clean, "source": "category"}

    # 5) heuristic — 가맹점명 키워드 휴리스틱(계정 무관 폴백). 지연 import 로 순환참조 회피.
    from app.agents.card_collect.nodes._shared import recommend_note

    h = recommend_note(merchant, amount=None)
    if h and h.strip():
        clean = sanitize_note(h.strip())
        if clean:
            return {"note": clean, "source": "heuristic"}
    # 6) 아무것도 없음 — 사다리 전체 미발견일 때만 None 반환(유일한 None exit).
    return {"note": None, "source": None}
