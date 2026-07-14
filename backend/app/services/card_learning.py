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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import (
    CardLearnedNote,
    CardLearnedSelection,
    CardSeedNote,
    CardSeedSelection,
)

logger = logging.getLogger("app.services.card_learning")

# 결정적 적용(Tier 1) 판정: 같은 가맹점을 이 횟수 이상 동일 확정했으면 AI 없이 그대로 프리필.
LEARNED_APPLY_MIN_COUNT = 3


def norm_merchant(name: str | None) -> str:
    """가맹점명 매칭 키 — 공백·괄호표기·부호를 흡수해 '네이버파이낸셜㈜'↔'네이버파이낸셜(주)' 등을 묶는다."""
    s = str(name or "")
    s = s.replace("㈜", "주식회사").replace("(주)", "주식회사").replace("（주）", "주식회사")
    s = re.sub(r"[\s()\[\]{}·・,./\-_'\"]+", "", s)
    return s.lower()


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
                note = (e.get("note") or "").strip() or None
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


async def suggest_note(
    session: AsyncSession,
    *,
    user_id: str | uuid.UUID | None,
    merchant: str,
    acct_code: str | None,
) -> dict:
    """(가맹점 × 계정) → 적요 리졸버 — learned>seed>category>heuristic 사다리(첫 히트 반환).

    반환 {"note": str|None, "source": "learned"|"seed"|"category"|"heuristic"|None}.
    계정(acct_code) 있으면 개인학습(CardLearnedNote, 가장 구체적) → 전사 seed(CardSeedNote,
    가맹점×계정) → 그 계정의 최빈 적요(CardSeedNote 를 acct_code 로 GROUP BY — cold-start:
    처음 보는 가맹점도 계정 카테고리 적요) 순으로 결정적 매칭하고, 못 찾으면 가맹점명 키워드
    휴리스틱으로 폴백. 계정 없으면 1·2·3 을 스킵하고 휴리스틱만.

    사람이 예산단위(=계정)를 바꿀 때 그 계정에 맞는 적요를 재추천하는 리졸버 — 엔드포인트
    GET /me/note-suggest 와 collect 초기 프리필이 공유해 배치 최초 추천·실시간 재추천이 일관된다.
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
            if learned_note and learned_note.strip():
                return {"note": learned_note.strip(), "source": "learned"}
        # 2) seed — (norm, acct) 전사 가맹점×계정 관례.
        if norm:
            seed_note = (
                (
                    await session.execute(
                        select(CardSeedNote.note)
                        .where(
                            CardSeedNote.norm_merchant == norm,
                            CardSeedNote.acct_code == acct,
                        )
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if seed_note and seed_note.strip():
                return {"note": seed_note.strip(), "source": "seed"}
        # 3) category — 그 계정의 최빈 적요(count 합 최대). 쿼리타임 집계, 별도 테이블 없음.
        total = func.sum(CardSeedNote.count)
        cat_note = (
            (
                await session.execute(
                    select(CardSeedNote.note)
                    .where(CardSeedNote.acct_code == acct, CardSeedNote.note.isnot(None))
                    .group_by(CardSeedNote.note)
                    .order_by(total.desc(), CardSeedNote.note.asc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if cat_note and cat_note.strip():
            return {"note": cat_note.strip(), "source": "category"}

    # 4) heuristic — 가맹점명 키워드 휴리스틱(계정 무관 폴백). 지연 import 로 순환참조 회피.
    from app.agents.card_collect.nodes._shared import recommend_note

    h = recommend_note(merchant, amount=None)
    if h and h.strip():
        return {"note": h.strip(), "source": "heuristic"}
    # 5) 아무것도 없음.
    return {"note": None, "source": None}
