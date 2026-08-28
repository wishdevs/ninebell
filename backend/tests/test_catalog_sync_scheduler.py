"""catalog_sync_scheduler 단위 테스트 — 시각 계산·세마포어 가드·상태 기록."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import catalog_sync_scheduler as sched


def test_parse_hhmm_valid_and_fallback():
    assert sched._parse_hhmm("04:30") == (4, 30)
    assert sched._parse_hhmm("23:59") == (23, 59)
    assert sched._parse_hhmm("nope") == (4, 30)  # 폴백
    assert sched._parse_hhmm("25:00") == (4, 30)  # 범위 밖 → 폴백


def test_seconds_until_today_and_tomorrow():
    now = datetime(2026, 8, 28, 3, 0, 0)
    # 04:30 은 오늘 → 1.5시간 뒤.
    assert sched._seconds_until(4, 30, now=now) == 90 * 60
    # 02:00 은 이미 지남 → 내일(23시간 뒤).
    assert sched._seconds_until(2, 0, now=now) == 23 * 3600


def _fake_app(*, locked: bool = False):
    sem = asyncio.Semaphore(1)
    if locked:
        # 슬롯을 미리 점유(수동 동기화 진행 중 상황).
        sem._value = 0  # noqa: SLF001 — 테스트에서 locked 상태를 직접 만든다.
    return SimpleNamespace(
        state=SimpleNamespace(
            catalog_sync_semaphore=sem,
            catalog_sync_state={},
            run_semaphore=None,
            browser_factory=None,
        )
    )


@pytest.mark.asyncio
async def test_guarded_sync_records_success(monkeypatch):
    app = _fake_app()

    async def _fake_sync(kind, userid, password, browser_factory, sessionmaker):
        return {"count": 7, "syncedAt": "2026-08-28T00:00:00+00:00", "via": "api"}

    monkeypatch.setattr(sched, "sync_catalog", _fake_sync)
    monkeypatch.setattr(sched, "get_sessionmaker", lambda: object())
    await sched._guarded_sync(app, "partner", "svc", "pw")
    st = app.state.catalog_sync_state["partner"]
    assert st["running"] is False and st["count"] == 7 and st["error"] is None
    assert app.state.catalog_sync_semaphore.locked() is False  # 반납됨


@pytest.mark.asyncio
async def test_guarded_sync_records_error(monkeypatch):
    app = _fake_app()

    async def _boom(*a, **k):
        raise RuntimeError("ERP 로그인 거부")

    monkeypatch.setattr(sched, "sync_catalog", _boom)
    monkeypatch.setattr(sched, "get_sessionmaker", lambda: object())
    await sched._guarded_sync(app, "project", "svc", "pw")
    st = app.state.catalog_sync_state["project"]
    assert st["error"] == "ERP 로그인 거부" and st["count"] is None
    assert app.state.catalog_sync_semaphore.locked() is False


@pytest.mark.asyncio
async def test_guarded_sync_skips_when_locked(monkeypatch):
    app = _fake_app(locked=True)
    called = {"n": 0}

    async def _fake_sync(*a, **k):
        called["n"] += 1
        return {"count": 0, "syncedAt": "x"}

    monkeypatch.setattr(sched, "sync_catalog", _fake_sync)
    monkeypatch.setattr(sched, "get_sessionmaker", lambda: object())
    await sched._guarded_sync(app, "partner", "svc", "pw")
    assert called["n"] == 0  # 진행 중이라 건너뜀
    st = app.state.catalog_sync_state["partner"]
    assert st["skipped"] is True and st["error"] is None  # 스킵을 관측 가능하게 기록


@pytest.mark.asyncio
async def test_run_daily_returns_when_disabled(monkeypatch):
    monkeypatch.setattr(
        sched, "get_settings",
        lambda: SimpleNamespace(erp_sync_daily_enabled=False, erp_sync_userid="", erp_sync_password=""),
    )
    # 비활성이면 즉시 리턴(무한 루프에 안 빠짐).
    await asyncio.wait_for(sched.run_daily_catalog_sync(_fake_app()), timeout=1)


@pytest.mark.asyncio
async def test_run_daily_returns_when_no_credentials(monkeypatch):
    monkeypatch.setattr(
        sched, "get_settings",
        lambda: SimpleNamespace(
            erp_sync_daily_enabled=True, erp_sync_userid="", erp_sync_password="",
            erp_sync_at="04:30", erp_sync_kind_list=lambda: ["partner"],
        ),
    )
    await asyncio.wait_for(sched.run_daily_catalog_sync(_fake_app()), timeout=1)
