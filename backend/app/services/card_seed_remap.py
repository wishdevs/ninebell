"""전사 시드(card_seed_notes)의 예산계정 코드를 현 ERP 카탈로그(9자리 bgacctCd)에 재키잉.

옛 기초자료(.xls)는 과거 5자리 계정과목 코드를 쓰는데 현 ERP 예산계정은 9자리 내부코드라
코드가 겹치지 않는다(정상 — 코드 체계가 다름). 프론트/collect 는 현 ERP 9자리 bgacctCd 로
적요를 조회하므로, 시드가 매칭되려면 **현 카탈로그 코드로 맞춰야** 한다. 시드의 안정적 정체성은
계정 '이름'이라, (계정이름 + 제/판 구분)으로 카탈로그 bgacctNm 을 찾아 acct_code 를 9자리로 갱신한다.

제/판(제조원가/판매관리비) 구분은 계정코드 선두 숫자로 판단한다: 5xxxx=제조, 8xxxx=판관.
이 관례는 옛 5자리·현 9자리 코드 모두에서 유지되므로(511…=제, 811…=판) 재실행에도 안정적이다.

멱등·재실행 가능: acct_name(불변 앵커)에서 매번 목표 코드를 재도출하므로, 카탈로그 재동기화로
ERP 코드가 바뀌어도 다시 정렬된다. 이름이 카탈로그에 없으면(폐지된 총괄계정 등) 원 코드를 그대로
두고(그 조합은 AI/category tier 가 커버) 넘어간다. budget_unit 카탈로그 동기화 완료 후 자동 호출.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CardSeedNote, ErpCodeCatalog

logger = logging.getLogger("app.services.card_seed_remap")

_JP_PREFIX = re.compile(r"^\s*\((제|판)\)\s*")
_PAREN_CLAUSE = re.compile(r"\s*\([^)]*\)")
_WS = re.compile(r"\s+")


def _norm_acct_name(name: str | None) -> str:
    """계정 이름 매칭 키 — 선두 (제)/(판)·나머지 괄호절·공백을 흡수한다.

    '(제)복리후생비-석식 (연장근무 식대)' ↔ '복리후생비-석식' 을 같은 키('복리후생비-석식')로 묶는다.
    '-'(세부 구분)는 보존 — '복리후생비-중식' vs '복리후생비-석식' 을 갈라야 하므로.
    """
    s = str(name or "")
    s = _JP_PREFIX.sub("", s)
    s = _PAREN_CLAUSE.sub("", s)
    s = _WS.sub("", s)
    return s.strip().lower()


def _acct_jp(code: str | None) -> str | None:
    """계정코드 선두로 제/판 구분 — 5xxxx=제조('제'), 8xxxx=판관('판'), 그 외 None(대상 아님)."""
    c = str(code or "").strip()
    if c[:1] == "5":
        return "제"
    if c[:1] == "8":
        return "판"
    return None


async def remap_seed_notes_to_catalog(session: AsyncSession) -> dict:
    """card_seed_notes.acct_code 를 현 ERP 카탈로그(budget_unit) 9자리 bgacctCd 로 재키잉.

    (제/판 + 정규화 이름)으로 카탈로그를 유니크 매칭할 때만 갱신한다. 다중매칭(같은 키에 서로 다른
    코드)·미매칭·이미 정렬됨·유니크 충돌은 건드리지 않는다. 반환 통계 dict(remapped/skipped/
    unmatched/ambiguous_skipped/collided). 호출자가 fresh 세션을 주입한다(내부에서 commit).
    """
    # 1) 카탈로그 인덱스: (jp, norm_name) → bgacctCd. 같은 키에 서로 다른 코드면 다중 → 제외.
    cat_extras = (
        (
            await session.execute(
                select(ErpCodeCatalog.extra).where(ErpCodeCatalog.kind == "budget_unit")
            )
        )
        .scalars()
        .all()
    )
    index: dict[tuple[str | None, str], str] = {}
    ambiguous: set[tuple[str | None, str]] = set()
    for extra in cat_extras:
        if not extra:
            continue
        code = (extra.get("bgacctCd") or "").strip()
        name = extra.get("bgacctNm") or ""
        if not code or not name:
            continue
        key = (_acct_jp(code), _norm_acct_name(name))
        if key in index and index[key] != code:
            ambiguous.add(key)
        else:
            index[key] = code
    for k in ambiguous:
        index.pop(k, None)

    # 2) 시드 재키잉. (norm_merchant, acct_code) 유니크라 in-memory 로 충돌을 방지한다.
    rows = (await session.execute(select(CardSeedNote))).scalars().all()
    claimed: set[tuple[str, str]] = {(r.norm_merchant, r.acct_code) for r in rows}

    remapped = skipped = unmatched = ambiguous_skipped = collided = 0
    for row in rows:
        key = (_acct_jp(row.acct_code), _norm_acct_name(row.acct_name))
        target = index.get(key)
        if target is None:
            if key in ambiguous:
                ambiguous_skipped += 1  # 같은 이름에 제/판으로도 안 갈리는 계정 → 안전하게 미변경.
            else:
                unmatched += 1
            continue
        if row.acct_code == target:
            skipped += 1
            continue
        if (row.norm_merchant, target) in claimed:
            collided += 1  # 같은 가맹점에 이미 그 9자리가 있음 → 유니크 충돌 회피.
            continue
        claimed.discard((row.norm_merchant, row.acct_code))
        claimed.add((row.norm_merchant, target))
        row.acct_code = target
        remapped += 1

    await session.commit()
    stats = {
        "remapped": remapped,
        "skipped": skipped,
        "unmatched": unmatched,
        "ambiguous_skipped": ambiguous_skipped,
        "collided": collided,
    }
    logger.info("card_seed_notes 재키잉: %s", stats)
    return stats
