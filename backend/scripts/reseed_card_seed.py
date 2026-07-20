"""커밋된 전사 시드(gz)를 DB 에 강제 재적재 — 시드 소스를 수정한 뒤 반영할 때 실행.

배경: `seed_card_seeds` 는 스타트업에서 **테이블이 비어있을 때만** gz 를 적재한다(누적 보존).
그래서 이미 시드된 DB(예: 로컬)는 커밋된 시드 gz 를 바꿔도 백엔드 재시작만으론 갱신되지 않고,
개입 학습 디버그(/dev/card-learning)의 '공통' 탭이 계속 옛 데이터를 보여준다. 이 스크립트는
card_seed_selections 를 gz 기준으로 **전량 교체**한다(런타임 누적이 없어 교체가 안전하다).

사용:
    cd backend && .venv/bin/python scripts/reseed_card_seed.py [--notes] [--dry]

    --dry    현재 건수만 출력하고 재적재하지 않음.
    --notes  card_seed_notes 도 함께 재적재. ⚠ ERP 재키잉(card_seed_remap, 9자리 bgacctCd)
             결과가 지워지므로 필요하면 remap 을 다시 돌릴 것.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_sessionmaker, init_engine  # noqa: E402
from app.models import CardSeedNote, CardSeedSelection  # noqa: E402
from app.services.seed import seed_card_seed_notes, seed_card_seeds  # noqa: E402


async def _count(session, model) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar() or 0)


async def main() -> None:
    do_notes = "--notes" in sys.argv
    dry = "--dry" in sys.argv
    init_engine(get_settings().database_url)
    async with get_sessionmaker()() as session:
        before_sel = await _count(session, CardSeedSelection)
        before_note = await _count(session, CardSeedNote)
        if dry:
            print(
                f"[--dry] card_seed_selections={before_sel}"
                + (f" · card_seed_notes={before_note}" if do_notes else "")
                + " — 재적재 미실행."
            )
            await dispose_engine()
            return
        await seed_card_seeds(session, force=True)
        if do_notes:
            await seed_card_seed_notes(session, force=True)
        await session.commit()
        after_sel = await _count(session, CardSeedSelection)
        after_note = await _count(session, CardSeedNote)
    print(f"card_seed_selections 재적재: {before_sel} → {after_sel}행")
    if do_notes:
        print(f"card_seed_notes 재적재: {before_note} → {after_note}행 (⚠ 필요 시 remap 재실행)")
    else:
        print("(card_seed_notes 는 미변경 — 재적재하려면 --notes)")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
