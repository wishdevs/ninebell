"""catalog_sync_scheduler 단위 테스트 — 항목별 주기 판정(due_kinds)·틱(세마포어 가드·순차 실행)·기동 가드."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import ErpSyncRun
from app.services import catalog_sync_scheduler as sched
from app.services import erp_sync


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


async def _seed_run(sm, kind: str, *, ago: timedelta, status: str = "succeeded") -> None:
    started = datetime.now(timezone.utc) - ago
    async with sm() as s:
        s.add(
            ErpSyncRun(
                kind=kind, trigger="scheduled", status=status, started_at=started,
                finished_at=None if status == "running" else started + timedelta(seconds=5),
            )
        )
        await s.commit()


async def _rows(sm) -> list[ErpSyncRun]:
    from sqlalchemy import select

    async with sm() as s:
        return list((await s.execute(select(ErpSyncRun).order_by(ErpSyncRun.id))).scalars().all())


@pytest.fixture
def scheduler_env(monkeypatch, sm):
    """스케줄러가 테스트 DB 를 쓰고 sync_catalog 는 fake — 호출 순서를 기록한다."""
    calls: list[str] = []

    async def _fake_sync(kind, userid, password, browser_factory, sessionmaker):
        calls.append(kind)
        return {"count": 1, "syncedAt": "2026-09-02T00:00:00+00:00", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake_sync)
    monkeypatch.setattr(sched, "get_sessionmaker", lambda: sm)
    return calls


# ── 주기 판정 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_due_kinds_all_when_no_history(sm):
    async with sm() as s:
        assert await sched.due_kinds(s) == ["budget_unit", "project", "partner", "org_unit"]


@pytest.mark.asyncio
async def test_due_kinds_waits_until_interval_elapsed(sm):
    # 기본 주기: 예산단위 1시간, ERP 조직 일주일.
    await _seed_run(sm, "budget_unit", ago=timedelta(minutes=10))
    await _seed_run(sm, "org_unit", ago=timedelta(days=3))
    async with sm() as s:
        assert await sched.due_kinds(s) == ["project", "partner"]


@pytest.mark.asyncio
async def test_due_kinds_runs_when_elapsed(sm):
    await _seed_run(sm, "budget_unit", ago=timedelta(hours=2))
    await _seed_run(sm, "org_unit", ago=timedelta(days=8))
    await _seed_run(sm, "project", ago=timedelta(minutes=1))
    await _seed_run(sm, "partner", ago=timedelta(minutes=1))
    async with sm() as s:
        assert await sched.due_kinds(s) == ["budget_unit", "org_unit"]


@pytest.mark.asyncio
async def test_due_kinds_failed_history_counts_as_last_attempt(sm):
    # 실패도 '마지막 실행 시작' — 즉시 재시도가 아니라 주기 뒤 재시도.
    await _seed_run(sm, "budget_unit", ago=timedelta(minutes=5), status="failed")
    await _seed_run(sm, "project", ago=timedelta(hours=3), status="failed")
    await _seed_run(sm, "partner", ago=timedelta(minutes=1))
    await _seed_run(sm, "org_unit", ago=timedelta(minutes=1))
    async with sm() as s:
        assert await sched.due_kinds(s) == ["project"]


@pytest.mark.asyncio
async def test_due_kinds_uses_saved_interval(sm):
    await _seed_run(sm, "budget_unit", ago=timedelta(hours=2))
    for kind in ("project", "partner", "org_unit"):
        await _seed_run(sm, kind, ago=timedelta(minutes=1))
    async with sm() as s:
        await erp_sync.save_interval(s, "budget_unit", 21600)  # 6시간
        assert await sched.due_kinds(s) == []  # 2시간 경과 < 6시간
        await erp_sync.save_interval(s, "budget_unit", 3600)
        assert await sched.due_kinds(s) == ["budget_unit"]


def test_is_due_and_next_run_at_pure():
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    assert erp_sync.next_run_at(None, 3600, now=now) == now
    assert erp_sync.is_due(None, 3600, now=now) is True
    last = now - timedelta(minutes=59)
    assert erp_sync.next_run_at(last, 3600, now=now) == last + timedelta(hours=1)
    assert erp_sync.is_due(last, 3600, now=now) is False
    assert erp_sync.is_due(now - timedelta(hours=1), 3600, now=now) is True
    # SQLite 가 주는 naive 시각도 UTC 로 간주해 비교된다.
    assert erp_sync.is_due(datetime(2026, 9, 2, 10, 0), 3600, now=now) is True


# ── 틱 ───────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tick_runs_due_kinds_sequentially_and_records(scheduler_env, sm):
    app = _fake_app()
    ran = await sched.tick(app, "svc", "pw")
    assert ran == ["budget_unit", "project", "partner", "org_unit"]
    assert scheduler_env == ran  # 순차·순서 보존
    rows = await _rows(sm)
    assert [r.kind for r in rows] == ran
    assert all(r.trigger == "scheduled" and r.status == "succeeded" for r in rows)
    assert app.state.catalog_sync_semaphore.locked() is False  # 반납됨
    assert app.state.catalog_sync_state["org_unit"]["running"] is False
    # 방금 실행됐으니 다음 틱은 대상 없음.
    assert await sched.tick(app, "svc", "pw") == []
    assert len(await _rows(sm)) == 4


@pytest.mark.asyncio
async def test_tick_skips_when_locked_without_history_row(scheduler_env, sm):
    app = _fake_app(locked=True)
    assert await sched.tick(app, "svc", "pw") == []
    assert scheduler_env == []  # 실행 없음
    assert await _rows(sm) == []  # 스킵 이력 행을 남기지 않는다
    assert app.state.catalog_sync_state == {}


@pytest.mark.asyncio
async def test_tick_records_failure_and_continues(monkeypatch, sm):
    app = _fake_app()

    async def _fake_sync(kind, *a, **k):
        if kind == "project":
            raise RuntimeError("ERP 로그인 거부")
        return {"count": 1, "syncedAt": "x", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake_sync)
    monkeypatch.setattr(sched, "get_sessionmaker", lambda: sm)
    assert await sched.tick(app, "svc", "pw") == ["budget_unit", "project", "partner", "org_unit"]
    rows = {r.kind: r for r in await _rows(sm)}
    assert rows["project"].status == "failed" and rows["project"].error == "ERP 로그인 거부"
    assert rows["partner"].status == "succeeded"
    assert app.state.catalog_sync_semaphore.locked() is False


# ── 기동 가드 ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_run_scheduler_returns_when_disabled(monkeypatch):
    monkeypatch.setattr(
        sched, "get_settings",
        lambda: SimpleNamespace(erp_sync_daily_enabled=False, erp_sync_userid="", erp_sync_password=""),
    )
    # 비활성이면 즉시 리턴(무한 루프에 안 빠짐).
    await asyncio.wait_for(sched.run_catalog_sync_scheduler(_fake_app()), timeout=1)


@pytest.mark.asyncio
async def test_run_scheduler_returns_when_no_credentials(monkeypatch):
    monkeypatch.setattr(
        sched, "get_settings",
        lambda: SimpleNamespace(erp_sync_daily_enabled=True, erp_sync_userid="", erp_sync_password=""),
    )
    await asyncio.wait_for(sched.run_catalog_sync_scheduler(_fake_app()), timeout=1)
