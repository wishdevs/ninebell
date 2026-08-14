"""card_seed_notes 를 현 ERP 카탈로그(budget_unit) 9자리 코드로 재키잉(수동 실행).

카탈로그(budget_unit)가 동기화된 상태에서 실행한다. 평소엔 budget_unit 카탈로그 동기화 후
자동 호출(code_sync)되지만, 기존 데이터를 즉시 1회 정렬하거나 진단할 때 이 스크립트를 쓴다.

    python -m scripts.remap_seed_notes         # backend/ 에서
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db import get_sessionmaker, init_engine
from app.services.card_seed_remap import remap_seed_notes_to_catalog


async def main() -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    async with get_sessionmaker()() as db:
        stats = await remap_seed_notes_to_catalog(db)
    print("card_seed_notes 재키잉 결과:", stats)


if __name__ == "__main__":
    asyncio.run(main())
