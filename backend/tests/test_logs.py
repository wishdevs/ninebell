"""GET /logs 페이지네이션 — dual-key envelope(logs+items 병기, limit/offset) 검증."""

from __future__ import annotations

import pytest

from app.models import AccessLog


async def _seed_logs(sm, n: int) -> None:
    async with sm() as s:
        for i in range(n):
            s.add(AccessLog(omnisol_userid=f"u{i:03d}", status="success"))
        await s.commit()


@pytest.mark.asyncio
async def test_logs_page_returns_total_and_limited_rows(client, make_user, auth_as, sm):
    """seed N개 → limit<N 요청 시 total==N, 반환 행은 limit 만큼."""
    await _seed_logs(sm, 7)
    uid = await make_user("root", "super_admin")
    auth_as(uid)

    r = await client.get("/logs?limit=3&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7
    assert len(body["logs"]) == 3


@pytest.mark.asyncio
async def test_logs_offset_paginates(client, make_user, auth_as, sm):
    """offset 으로 다음 페이지를 받아도 total 은 동일하고 남은 행만큼 반환."""
    await _seed_logs(sm, 7)
    uid = await make_user("root", "super_admin")
    auth_as(uid)

    r = await client.get("/logs?limit=5&offset=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7
    assert len(body["logs"]) == 2


@pytest.mark.asyncio
async def test_logs_empty_total_zero(client, make_user, auth_as):
    """로그가 없으면 total==0, logs==[]."""
    uid = await make_user("root", "super_admin")
    auth_as(uid)

    r = await client.get("/logs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["logs"] == []


@pytest.mark.asyncio
async def test_logs_dual_key_items_mirrors_logs(client, make_user, auth_as, sm):
    """dual-key: 구 키(logs)와 표준 키(items)가 같은 목록 + limit/offset 에코.

    FE 전환 후 별도 커밋에서 logs 키 제거 예정(docs/LIST-COMMONALIZATION.md).
    """
    await _seed_logs(sm, 4)
    uid = await make_user("root", "super_admin")
    auth_as(uid)

    body = (await client.get("/logs?limit=3&offset=1")).json()
    assert body["items"] == body["logs"]
    assert len(body["items"]) == 3
    assert body["limit"] == 3
    assert body["offset"] == 1
