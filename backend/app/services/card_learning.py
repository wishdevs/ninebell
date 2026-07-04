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

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import CardLearnedSelection, CardSeedSelection

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
