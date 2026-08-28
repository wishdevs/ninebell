"""code_sync 의 API 우선·브라우저 폴백 결정 로직 + upsert stale 보호 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.erp import api_client
from app.erp.api_client import ErpApiError
from app.models import ErpCodeCatalog
from app.services import code_sync


class _SettingsStub:
    def __init__(self, enabled: bool):
        self.erp_api_sync_enabled = enabled


def _boom_factory():
    async def _factory():
        raise AssertionError("browser_factory 가 호출되면 안 됨(API 성공 경로)")

    return _factory


# ── _collect_rows: API 우선 / 폴백 ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_collect_rows_api_success_skips_browser(monkeypatch):
    monkeypatch.setattr(code_sync, "get_settings", lambda: _SettingsStub(enabled=True))

    async def _fake_api(kind, userid, password):
        return [{"code": "X", "name": "n"}]

    monkeypatch.setattr(api_client, "fetch_catalog_rows", _fake_api)
    rows, via = await code_sync._collect_rows("partner", "u", "p", _boom_factory())
    assert via == "api"
    assert rows == [{"code": "X", "name": "n"}]


@pytest.mark.asyncio
async def test_collect_rows_api_error_falls_back_to_browser(monkeypatch):
    monkeypatch.setattr(code_sync, "get_settings", lambda: _SettingsStub(enabled=True))

    async def _fail_api(kind, userid, password):
        raise ErpApiError("ERP 조회 HTTP 500")

    called = {}

    async def _fake_browser(kind, userid, password, browser_factory):
        called["kind"] = kind
        return [{"code": "B", "name": "browser"}]

    monkeypatch.setattr(api_client, "fetch_catalog_rows", _fail_api)
    monkeypatch.setattr(code_sync, "_browser_collect_rows", _fake_browser)
    rows, via = await code_sync._collect_rows("budget_unit", "u", "p", object())
    assert via == "browser"
    assert called["kind"] == "budget_unit"
    assert rows == [{"code": "B", "name": "browser"}]


@pytest.mark.asyncio
async def test_collect_rows_disabled_flag_uses_browser(monkeypatch):
    monkeypatch.setattr(code_sync, "get_settings", lambda: _SettingsStub(enabled=False))

    def _api_must_not_run(*a, **k):
        raise AssertionError("erp_api_sync_enabled=False 인데 API 가 호출됨")

    monkeypatch.setattr(api_client, "fetch_catalog_rows", _api_must_not_run)

    async def _fake_browser(kind, userid, password, browser_factory):
        return [{"code": "B", "name": "b"}]

    monkeypatch.setattr(code_sync, "_browser_collect_rows", _fake_browser)
    rows, via = await code_sync._collect_rows("project", "u", "p", object())
    assert via == "browser"


@pytest.mark.asyncio
async def test_collect_rows_api_fail_no_browser_factory_raises(monkeypatch):
    monkeypatch.setattr(code_sync, "get_settings", lambda: _SettingsStub(enabled=True))

    async def _fail_api(kind, userid, password):
        raise ErpApiError("net")

    monkeypatch.setattr(api_client, "fetch_catalog_rows", _fail_api)
    with pytest.raises(RuntimeError, match="브라우저 폴백 불가"):
        await code_sync._collect_rows("partner", "u", "p", None)


# ── upsert stale 보호 ────────────────────────────────────────────────────────
async def _seed_catalog(sm, kind: str, codes: list[str]) -> None:
    now = datetime.now(timezone.utc)
    async with sm() as s:
        for c in codes:
            s.add(ErpCodeCatalog(kind=kind, dept="", code=c, name=c, extra={}, synced_at=now))
        await s.commit()


async def _count(sm, kind: str) -> int:
    async with sm() as s:
        return (
            await s.execute(select(func.count()).select_from(ErpCodeCatalog).where(ErpCodeCatalog.kind == kind))
        ).scalar() or 0


@pytest.mark.asyncio
async def test_upsert_budget_units_inserts(sm):
    rows = [
        {"code": "B1|P|A", "name": "팀", "bizplanCd": "P", "bizplanNm": "", "bgacctCd": "A", "bgacctNm": ""},
    ]
    n = await code_sync._upsert_budget_units(rows, sm)
    assert n == 1
    assert await _count(sm, "budget_unit") == 1


@pytest.mark.asyncio
async def test_upsert_budget_units_skips_stale_delete_when_fewer(sm):
    """부분(잘린) 결과가 전량 예산단위 카탈로그를 지우지 않는다(project/partner 미러)."""
    await _seed_catalog(sm, "budget_unit", ["b1|p|a", "b2|p|a", "b3|p|a"])
    rows = [{"code": "b1|p|a", "name": "x", "bizplanCd": "p", "bgacctCd": "a"}]  # 1 < 3
    await code_sync._upsert_budget_units(rows, sm)
    assert await _count(sm, "budget_unit") == 3  # 보존


@pytest.mark.asyncio
async def test_upsert_projects_skips_stale_delete_when_fewer(sm):
    await _seed_catalog(sm, "project", ["p1|", "p2|", "p3|"])
    # 신규 2건 < 기존 3건 → stale 삭제 생략(부분 수집 보호): 기존 3건 보존.
    rows = [{"code": "p1|", "name": "a", "pjtNo": "p1"}, {"code": "p2|", "name": "b", "pjtNo": "p2"}]
    await code_sync._upsert_projects(rows, sm)
    assert await _count(sm, "project") == 3


@pytest.mark.asyncio
async def test_upsert_projects_deletes_stale_when_ge(sm):
    await _seed_catalog(sm, "project", ["p1|", "p2|"])
    # 신규 3건 >= 기존 2건 → stale 삭제 적용. p2 는 신규에 없으므로 삭제, p9 추가.
    rows = [
        {"code": "p1|", "name": "a", "pjtNo": "p1"},
        {"code": "p3|", "name": "c", "pjtNo": "p3"},
        {"code": "p9|", "name": "i", "pjtNo": "p9"},
    ]
    await code_sync._upsert_projects(rows, sm)
    async with sm() as s:
        codes = set(
            (await s.execute(select(ErpCodeCatalog.code).where(ErpCodeCatalog.kind == "project"))).scalars().all()
        )
    assert codes == {"p1|", "p3|", "p9|"}  # p2 삭제됨


@pytest.mark.asyncio
async def test_upsert_partners_empty_with_existing_raises(sm):
    await _seed_catalog(sm, "partner", ["c1", "c2"])
    with pytest.raises(RuntimeError, match="비어 있습니다"):
        await code_sync._upsert_partners([], sm)
    assert await _count(sm, "partner") == 2  # 보존


@pytest.mark.asyncio
async def test_upsert_partners_empty_fresh_returns_zero(sm):
    assert await code_sync._upsert_partners([], sm) == 0
