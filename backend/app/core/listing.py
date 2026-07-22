"""공용 리스트 조회 레일 — 페이지 파라미터 의존성 + count·rows 페이지네이터.

기존 3중복 수동 clamp(me_codes.py:308-309 / me_codes.py:470-471 / runs.py:515-516)와
count·rows 이중 필터 조립(logs.py:36-40, me_codes.py:301-307)을 대체한다.
정렬 레일(apply_sort)은 보류 — docs/LIST-COMMONALIZATION.md 참조.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 50
MAX_LIMIT = 200  # logs.py:23 의 le=200 과 동일 상한.

T = TypeVar("T")


@dataclass(frozen=True)
class PageParams:
    limit: int = DEFAULT_LIMIT
    offset: int = 0


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    """수동 clamp 대신 FastAPI Query 검증(범위 밖=422)으로 통일."""
    return PageParams(limit=limit, offset=offset)


PageQuery = Annotated[PageParams, Depends(page_params)]


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


async def paginate(db: AsyncSession, stmt: Select, page: PageParams) -> Page:
    """필터가 붙은 rows 쿼리 하나에서 count 를 파생 — 조건을 두 번 붙이지 않는다."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    return Page(items=list(rows), total=int(total), limit=page.limit, offset=page.offset)


def page_slice(rows: Sequence[T], page: PageParams) -> Page[T]:
    """파이썬 인메모리 필터 경로(/me/catalog, me_codes.py:538) 전용 — envelope 만 통일."""
    return Page(
        items=list(rows[page.offset : page.offset + page.limit]),
        total=len(rows),
        limit=page.limit,
        offset=page.offset,
    )
