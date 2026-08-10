"""공용 리스트 레일(app/core/listing.py) — page_slice 경계·paginate count 파생·page_params 422."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.listing import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PageParams,
    PageQuery,
    page_slice,
    paginate,
)
from app.models import AccessLog

# ── page_slice — 인메모리 경로 경계 ─────────────────────────────────────────


def test_page_slice_empty_rows():
    """빈 목록 → items 빈 리스트, total 0. limit/offset 은 요청값 그대로."""
    page = page_slice([], PageParams(limit=10, offset=0))
    assert page.items == []
    assert page.total == 0
    assert page.limit == 10
    assert page.offset == 0


def test_page_slice_offset_beyond_total():
    """offset 이 전체 건수를 넘으면 빈 페이지 — total 은 전체 건수 유지."""
    page = page_slice(list(range(5)), PageParams(limit=10, offset=100))
    assert page.items == []
    assert page.total == 5


def test_page_slice_last_page_partial():
    """마지막 페이지는 남은 행만 반환(7건, limit=3, offset=6 → 1건)."""
    page = page_slice(list(range(7)), PageParams(limit=3, offset=6))
    assert page.items == [6]
    assert page.total == 7


def test_page_params_defaults():
    """PageParams 기본값 — DEFAULT_LIMIT / offset 0."""
    p = PageParams()
    assert p.limit == DEFAULT_LIMIT
    assert p.offset == 0


# ── paginate — 실 세션에서 count 파생 검증 ──────────────────────────────────


async def _seed_logs(sm, n: int) -> None:
    """AccessLog n건 삽입 — 짝수 인덱스 success, 홀수 failed(필터 count 검증용)."""
    async with sm() as s:
        for i in range(n):
            s.add(
                AccessLog(
                    omnisol_userid=f"u{i:03d}",
                    status="success" if i % 2 == 0 else "failed",
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_paginate_total_and_items(sm):
    """seed 7건 → limit=3 페이지: total 은 전체 7, items 는 3건(정렬순 유지)."""
    await _seed_logs(sm, 7)
    stmt = select(AccessLog).order_by(AccessLog.omnisol_userid)
    async with sm() as s:
        page = await paginate(s, stmt, PageParams(limit=3, offset=0))
    assert page.total == 7
    assert [r.omnisol_userid for r in page.items] == ["u000", "u001", "u002"]
    assert page.limit == 3
    assert page.offset == 0


@pytest.mark.asyncio
async def test_paginate_offset_last_page(sm):
    """offset 으로 마지막 페이지 요청 시 남은 행만 반환하고 total 은 동일."""
    await _seed_logs(sm, 7)
    stmt = select(AccessLog).order_by(AccessLog.omnisol_userid)
    async with sm() as s:
        page = await paginate(s, stmt, PageParams(limit=5, offset=5))
    assert page.total == 7
    assert [r.omnisol_userid for r in page.items] == ["u005", "u006"]


@pytest.mark.asyncio
async def test_paginate_count_follows_where(sm):
    """stmt 에 where 를 붙이면 count 도 같은 필터로 파생 — 이중 조립이 필요 없다."""
    await _seed_logs(sm, 7)  # success 4건(0·2·4·6), failed 3건
    stmt = (
        select(AccessLog)
        .where(AccessLog.status == "success")
        .order_by(AccessLog.omnisol_userid)
    )
    async with sm() as s:
        page = await paginate(s, stmt, PageParams(limit=2, offset=0))
    assert page.total == 4
    assert len(page.items) == 2
    assert all(r.status == "success" for r in page.items)


# ── page_params — FastAPI Query 검증(범위 밖=422, 수동 clamp 대체) ──────────

_rail_app = FastAPI()


@_rail_app.get("/items")
async def _list_items(page: PageQuery) -> dict:
    return {"limit": page.limit, "offset": page.offset}


@pytest_asyncio.fixture
async def rail_client():
    """PageQuery 만 노출하는 미니 앱 클라이언트 — 라우터 무접촉으로 의존성만 검증."""
    transport = ASGITransport(app=_rail_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_page_params_query_defaults(rail_client):
    """파라미터 생략 시 DEFAULT_LIMIT/0 이 주입된다."""
    r = await rail_client.get("/items")
    assert r.status_code == 200
    assert r.json() == {"limit": DEFAULT_LIMIT, "offset": 0}


@pytest.mark.asyncio
async def test_page_params_boundary_accepted(rail_client):
    """경계값(limit=1·MAX_LIMIT, offset=0)은 통과."""
    r = await rail_client.get(f"/items?limit={MAX_LIMIT}&offset=0")
    assert r.status_code == 200
    assert r.json() == {"limit": MAX_LIMIT, "offset": 0}

    r = await rail_client.get("/items?limit=1")
    assert r.status_code == 200
    assert r.json()["limit"] == 1


@pytest.mark.asyncio
async def test_page_params_out_of_range_422(rail_client):
    """범위 밖(limit 0/상한 초과, offset 음수)은 clamp 없이 422."""
    for qs in ("limit=0", f"limit={MAX_LIMIT + 1}", "offset=-1"):
        r = await rail_client.get(f"/items?{qs}")
        assert r.status_code == 422, qs
