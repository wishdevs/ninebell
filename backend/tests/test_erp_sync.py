"""ERP 동기화 통합 관리 — 공용 러너(services.erp_sync) + /admin/erp-sync 라우터 테스트.

- 러너: 성공/실패/건너뜀이 erp_sync_runs 이력 + RAM 상태에 남는다, 세마포어 반납, launch 즉시 running 행.
- 자격증명 폴백: 세션 우선 → 서비스 계정 → 없음(409/400), org_unit 로컬 계정 예외.
- API: GET 응답 shape(schedule/credentialSource/items 4종 순서 + intervalSeconds/nextRunAt), 403,
  POST 422/409/400, all 순차, PATCH 주기 저장(검증·기본값·반영).
sync_catalog 는 fake 로 주입(실 ERP 미접속).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.main import app as fastapi_app
from app.models import ErpCodeCatalog, ErpSyncRun, User
from app.routers import erp_sync as erp_sync_router
from app.services import catalog_sync_scheduler as sched
from app.services import erp_sync

# ── 헬퍼 ─────────────────────────────────────────────────────────────────────
def _settings(**over) -> SimpleNamespace:
    base = dict(
        erp_sync_daily_enabled=True,
        erp_sync_userid="svc",
        erp_sync_password="svc-pw",
        erp_sync_tz="Asia/Seoul",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fake_app(*, locked: bool = False) -> SimpleNamespace:
    sem = asyncio.Semaphore(1)
    if locked:
        sem._value = 0  # noqa: SLF001 — 진행 중 상태를 직접 만든다.
    return SimpleNamespace(
        state=SimpleNamespace(
            catalog_sync_semaphore=sem, catalog_sync_state={}, run_semaphore=None, browser_factory=None
        )
    )


def _ok_sync(count: int = 5, **extra):
    async def _fake(kind, userid, password, browser_factory, sessionmaker):
        return {"count": count, "syncedAt": "2026-09-02T00:00:00+00:00", "via": "api", **extra}

    return _fake


async def _rows(sm, kind: str | None = None) -> list[ErpSyncRun]:
    async with sm() as s:
        stmt = select(ErpSyncRun).order_by(ErpSyncRun.id.asc())
        if kind:
            stmt = stmt.where(ErpSyncRun.kind == kind)
        return list((await s.execute(stmt)).scalars().all())


async def _drain_tasks() -> None:
    """launch 가 띄운 백그라운드 태스크가 끝날 때까지 대기."""
    while erp_sync._TASKS:  # noqa: SLF001
        await asyncio.gather(*list(erp_sync._TASKS), return_exceptions=True)  # noqa: SLF001


@pytest.fixture(autouse=True)
def _clean_app_state():
    """앱 전역 RAM 상태(catalog_sync_state)가 테스트 간에 새지 않게."""
    fastapi_app.state.catalog_sync_state.clear()
    yield
    fastapi_app.state.catalog_sync_state.clear()


# ── 러너 ──────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_execute_kind_records_success_row_and_state(sm, monkeypatch):
    app = _fake_app()
    monkeypatch.setattr(erp_sync, "sync_catalog", _ok_sync(9, applied={"added": 2}, reassigned=3))
    ok = await erp_sync.execute_kind(
        app, "org_unit", "u", "p", trigger=erp_sync.TRIGGER_SCHEDULED, sessionmaker=sm
    )
    assert ok is True
    (row,) = await _rows(sm)
    assert row.kind == "org_unit" and row.trigger == "scheduled" and row.status == "succeeded"
    assert row.count == 9 and row.finished_at is not None and row.error is None
    assert row.extra == {"via": "api", "applied": {"added": 2}, "reassigned": 3}
    st = app.state.catalog_sync_state["org_unit"]
    assert st["running"] is False and st["count"] == 9 and st["reassigned"] == 3


@pytest.mark.asyncio
async def test_execute_kind_records_failure(sm, monkeypatch):
    app = _fake_app()

    async def _boom(*a, **k):
        raise RuntimeError("ERP 로그인 거부")

    monkeypatch.setattr(erp_sync, "sync_catalog", _boom)
    ok = await erp_sync.execute_kind(
        app, "project", "u", "p", trigger=erp_sync.TRIGGER_MANUAL, sessionmaker=sm
    )
    assert ok is False
    (row,) = await _rows(sm)
    assert row.status == "failed" and row.error == "ERP 로그인 거부" and row.count is None
    assert app.state.catalog_sync_state["project"]["error"] == "ERP 로그인 거부"


@pytest.mark.asyncio
async def test_run_kinds_sequential_and_releases_semaphore(sm, monkeypatch):
    app = _fake_app()
    await app.state.catalog_sync_semaphore.acquire()
    order: list[str] = []

    async def _fake(kind, *a, **k):
        order.append(kind)
        if kind == "project":
            raise RuntimeError("중간 실패")
        return {"count": 1, "syncedAt": "x", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake)
    jobs = [(k, "u", "p") for k in ("budget_unit", "project", "partner")]
    await erp_sync.run_kinds(app, jobs, trigger=erp_sync.TRIGGER_MANUAL, sessionmaker=sm)
    assert order == ["budget_unit", "project", "partner"]  # 실패해도 다음 kind 로 계속
    assert [r.status for r in await _rows(sm)] == ["succeeded", "failed", "succeeded"]
    assert app.state.catalog_sync_semaphore.locked() is False


@pytest.mark.asyncio
async def test_launch_opens_running_row_immediately_then_finishes(sm, monkeypatch):
    app = _fake_app()
    gate = asyncio.Event()

    async def _slow(kind, *a, **k):
        await gate.wait()
        return {"count": 3, "syncedAt": "x", "via": "browser"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _slow)
    started = await erp_sync.launch(
        app, [("budget_unit", "u", "p")], trigger=erp_sync.TRIGGER_MANUAL, sessionmaker=sm
    )
    assert started is True
    # 시작 즉시 running 행 + RAM running + 슬롯 점유.
    (row,) = await _rows(sm)
    assert row.status == "running" and row.finished_at is None
    assert app.state.catalog_sync_state["budget_unit"]["running"] is True
    assert app.state.catalog_sync_semaphore.locked() is True
    assert await erp_sync.launch(app, [("project", "u", "p")], trigger="manual", sessionmaker=sm) is False
    gate.set()
    await _drain_tasks()
    (row,) = await _rows(sm)
    assert row.status == "succeeded" and row.count == 3 and row.extra == {"via": "browser"}
    assert app.state.catalog_sync_semaphore.locked() is False


@pytest.mark.asyncio
async def test_reconcile_stale_runs_closes_running_rows(sm):
    async with sm() as s:
        s.add(ErpSyncRun(kind="partner", trigger="manual", status="running", started_at=datetime.now(timezone.utc)))
        s.add(ErpSyncRun(kind="project", trigger="manual", status="succeeded", started_at=datetime.now(timezone.utc)))
        await s.commit()
    assert await erp_sync.reconcile_stale_runs(sm) == 1
    rows = {r.kind: r for r in await _rows(sm)}
    assert rows["partner"].status == "failed" and rows["partner"].error == erp_sync.STALE_RUN_ERROR
    assert rows["project"].status == "succeeded"


# ── 자격증명 폴백 ─────────────────────────────────────────────────────────────
def _user(*, local: bool = False) -> SimpleNamespace:
    return SimpleNamespace(omnisol_userid="admin1", password_hash="hash" if local else None)


def test_resolve_credentials_session_first_then_service():
    s = _settings()
    assert erp_sync.resolve_credentials("project", _user(), "sess-pw", s) == ("admin1", "sess-pw", "session")
    assert erp_sync.resolve_credentials("project", _user(), None, s) == ("svc", "svc-pw", "service")


def test_resolve_credentials_local_account_never_uses_session_password():
    """로컬 계정(password_hash 있음, admin) 의 CredCache 비밀번호는 대시보드 비밀번호라 ERP 자격증명이
    아니다 — 세션 비밀번호가 있어도 서비스 계정으로, 서비스 계정도 없으면 409(서비스 계정 안내)."""
    assert erp_sync.resolve_credentials("partner", _user(local=True), "1111", _settings()) == (
        "svc", "svc-pw", "service",
    )
    with pytest.raises(erp_sync.CredentialError) as ei:
        erp_sync.resolve_credentials("partner", _user(local=True), "1111", _settings(erp_sync_userid=""))
    assert ei.value.status_code == 409 and "서비스 계정" in ei.value.message
    assert "다시 로그인" not in ei.value.message  # 재로그인은 해결책이 아니다


def test_resolve_credentials_erp_account_uses_session_password():
    """실 ERP 계정(password_hash None) 의 세션 비밀번호는 서비스 계정보다 우선한다."""
    assert erp_sync.resolve_credentials("partner", _user(), "erp-pw", _settings()) == (
        "admin1", "erp-pw", "session",
    )
    assert erp_sync.resolve_credentials("org_unit", _user(), "erp-pw", _settings()) == (
        "admin1", "erp-pw", "session",
    )


def test_resolve_credentials_org_unit_local_account_uses_service_or_400():
    s = _settings()
    assert erp_sync.resolve_credentials("org_unit", _user(local=True), "sess-pw", s)[2] == "service"
    assert erp_sync.resolve_credentials("org_unit", _user(), "sess-pw", s)[2] == "session"
    with pytest.raises(erp_sync.CredentialError) as ei:
        erp_sync.resolve_credentials("org_unit", _user(local=True), "sess-pw", _settings(erp_sync_userid=""))
    assert ei.value.status_code == 400 and "실제 ERP 계정" in ei.value.message


def test_resolve_credentials_none_is_409():
    with pytest.raises(erp_sync.CredentialError) as ei:
        erp_sync.resolve_credentials("project", _user(), None, _settings(erp_sync_password=""))
    assert ei.value.status_code == 409 and "자격증명" in ei.value.message


def test_credential_source():
    assert erp_sync.credential_source(_user(), "pw", _settings()) == "session"
    assert erp_sync.credential_source(_user(local=True), "pw", _settings()) == "service"
    assert erp_sync.credential_source(_user(), None, _settings()) == "service"
    assert erp_sync.credential_source(_user(), None, _settings(erp_sync_userid="")) is None
    assert erp_sync.credential_source(_user(local=True), "1111", _settings(erp_sync_userid="")) is None


def test_schedule_status_active_and_inactive():
    active = sched.schedule_status(_settings())
    assert set(active) == {"enabled", "serviceAccountConfigured", "active", "tz", "intervalOptions"}
    assert active["active"] is True and active["serviceAccountConfigured"] is True
    assert active["tz"] == "Asia/Seoul"
    assert [o["seconds"] for o in active["intervalOptions"]] == [
        3600, 21600, 43200, 86400, 259200, 604800, 2592000,
    ]
    assert active["intervalOptions"][0] == {"seconds": 3600, "label": "1시간"}
    assert active["intervalOptions"][-1]["label"] == "한달"
    inactive = sched.schedule_status(_settings(erp_sync_password=""))
    assert inactive["enabled"] is True and inactive["active"] is False
    assert inactive["serviceAccountConfigured"] is False
    assert "svc" not in str(active) and "svc-pw" not in str(active)  # 값 미노출


# ── API ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def api_settings(monkeypatch):
    """라우터가 읽는 설정을 고정(로컬 .env 의 ERP_SYNC_* 에 영향받지 않게)."""

    def _set(**over):
        s = _settings(**over)
        monkeypatch.setattr(erp_sync_router, "get_settings", lambda: s)
        return s

    return _set


@pytest.fixture
def session_password(monkeypatch):
    def _set(value: str | None):
        monkeypatch.setattr(erp_sync_router, "omnisol_password", lambda request: value)

    return _set


async def test_overview_requires_admin(client, make_user, auth_as, api_settings):
    api_settings()
    auth_as(await make_user("es-user", "user"))
    assert (await client.get("/admin/erp-sync")).status_code == 403
    assert (await client.post("/admin/erp-sync/project")).status_code == 403
    assert (await client.get("/admin/erp-sync/runs")).status_code == 403


async def test_overview_shape(client, make_user, auth_as, sm, api_settings, session_password):
    api_settings()
    session_password(None)
    uid = await make_user("es-admin", "admin")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    async with sm() as s:
        s.add(ErpCodeCatalog(kind="project", dept="", code="P1", name="p", synced_at=now - timedelta(days=3)))
        s.add(ErpCodeCatalog(kind="project", dept="", code="P2", name="q", synced_at=now - timedelta(days=3)))
        s.add(ErpCodeCatalog(kind="partner", dept="", code="C1", name="c", synced_at=now - timedelta(days=9)))
        s.add(ErpSyncRun(kind="project", trigger="scheduled", status="failed", started_at=now - timedelta(days=2),
                         finished_at=now - timedelta(days=2), error="boom"))
        s.add(ErpSyncRun(kind="project", trigger="manual", status="succeeded", started_at=now - timedelta(days=1),
                         finished_at=now - timedelta(days=1), count=2, actor_user_id=uid, extra={"via": "api"}))
        s.add(ErpSyncRun(kind="org_unit", trigger="manual", status="succeeded", started_at=now - timedelta(hours=1),
                         finished_at=now - timedelta(hours=1), count=7, actor_user_id=uid,
                         extra={"via": "browser", "applied": {"added": 1}, "reassigned": 3}))
        await s.commit()

    body = (await client.get("/admin/erp-sync")).json()
    assert set(body) == {"schedule", "credentialSource", "items"}
    assert body["credentialSource"] == "service"
    assert body["schedule"]["active"] is True and len(body["schedule"]["intervalOptions"]) == 7
    assert [i["kind"] for i in body["items"]] == ["budget_unit", "project", "partner", "org_unit"]
    # 주기: 저장값 없음 → 기본값(1시간, ERP 조직 일주일). 다음 실행 = 마지막 실행 시작 + 주기.
    assert [i["intervalSeconds"] for i in body["items"]] == [3600, 3600, 3600, 604800]
    by = {i["kind"]: i for i in body["items"]}
    assert by["project"]["label"] == "프로젝트" and by["project"]["count"] == 2
    assert by["project"]["running"] is False
    # 성공 이력이 있으면 그 finished_at(최근 succeeded).
    assert datetime.fromisoformat(by["project"]["lastSuccessAt"]) > now - timedelta(days=1, minutes=1)
    last = by["project"]["lastRun"]
    assert last["trigger"] == "manual" and last["status"] == "succeeded" and last["count"] == 2
    assert last["actorName"] == "es-admin" and last["error"] is None and last["applied"] is None
    assert set(last) == {"id", "kind", "trigger", "status", "startedAt", "finishedAt", "count", "error",
                         "applied", "reassigned", "actorName"}
    # 이력 없는 kind 는 카탈로그 synced_at 폴백 / 아예 없으면 null.
    assert datetime.fromisoformat(by["partner"]["lastSuccessAt"]) < now - timedelta(days=8)
    assert by["partner"]["lastRun"] is None
    assert by["budget_unit"]["lastSuccessAt"] is None and by["budget_unit"]["count"] == 0
    assert by["org_unit"]["lastRun"]["applied"] == {"added": 1} and by["org_unit"]["lastRun"]["reassigned"] == 3
    # nextRunAt: 이력 없음 → 지금(≈now), 있음 → 최근 실행 startedAt + 주기(상태 무관·최근 행 기준).
    assert abs(datetime.fromisoformat(by["budget_unit"]["nextRunAt"]) - now) < timedelta(seconds=30)
    assert datetime.fromisoformat(by["project"]["nextRunAt"]) == (
        datetime.fromisoformat(by["project"]["lastRun"]["startedAt"]) + timedelta(hours=1)
    )
    assert datetime.fromisoformat(by["org_unit"]["nextRunAt"]) == (
        datetime.fromisoformat(by["org_unit"]["lastRun"]["startedAt"]) + timedelta(days=7)
    )
    assert set(by["partner"]) == {"kind", "label", "running", "count", "lastSuccessAt", "lastRun",
                                  "intervalSeconds", "nextRunAt"}


async def test_overview_next_run_null_when_scheduler_inactive(client, make_user, auth_as, api_settings, session_password):
    api_settings(erp_sync_password="")
    session_password(None)
    auth_as(await make_user("es-admin-inactive", "admin"))
    body = (await client.get("/admin/erp-sync")).json()
    assert body["schedule"]["active"] is False
    assert all(i["nextRunAt"] is None for i in body["items"])
    assert [i["intervalSeconds"] for i in body["items"]] == [3600, 3600, 3600, 604800]


async def test_patch_interval_validation_and_persist(client, make_user, auth_as, sm, api_settings, session_password):
    api_settings()
    session_password(None)
    uid = await make_user("es-admin-patch", "admin")
    auth_as(uid)
    assert (await client.patch("/admin/erp-sync/nope", json={"intervalSeconds": 3600})).status_code == 422
    resp = await client.patch("/admin/erp-sync/budget_unit", json={"intervalSeconds": 1234})
    assert resp.status_code == 422 and "주기" in resp.json()["error"]
    assert (await client.patch("/admin/erp-sync/budget_unit", json={})).status_code == 422
    # 이력 1건(30분 전) → 저장 후 nextRunAt = startedAt + 6시간.
    started = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with sm() as s:
        s.add(ErpSyncRun(kind="budget_unit", trigger="manual", status="failed", started_at=started,
                         finished_at=started, error="x"))
        await s.commit()
    resp = await client.patch("/admin/erp-sync/budget_unit", json={"intervalSeconds": 21600})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "budget_unit" and body["intervalSeconds"] == 21600
    assert datetime.fromisoformat(body["nextRunAt"]) == started.replace(microsecond=started.microsecond) + timedelta(hours=6)
    # GET 반영 + 다른 kind 는 기본값 유지.
    items = {i["kind"]: i for i in (await client.get("/admin/erp-sync")).json()["items"]}
    assert items["budget_unit"]["intervalSeconds"] == 21600
    assert items["budget_unit"]["nextRunAt"] == body["nextRunAt"]
    assert items["project"]["intervalSeconds"] == 3600 and items["org_unit"]["intervalSeconds"] == 604800
    # 재저장은 행을 갱신(중복 행 없음) + updated_by 기록.
    assert (await client.patch("/admin/erp-sync/budget_unit", json={"intervalSeconds": 3600})).status_code == 200
    from app.models import ErpSyncSetting

    async with sm() as s:
        rows = (await s.execute(select(ErpSyncSetting))).scalars().all()
    assert len(rows) == 1 and rows[0].interval_seconds == 3600 and rows[0].updated_by == uid
    # 스케줄러 판정도 저장값을 본다.
    async with sm() as s:
        assert await erp_sync.load_intervals(s) == {
            "budget_unit": 3600, "project": 3600, "partner": 3600, "org_unit": 604800,
        }


async def test_patch_interval_requires_admin(client, make_user, auth_as, api_settings):
    api_settings()
    auth_as(await make_user("es-user-patch", "user"))
    assert (await client.patch("/admin/erp-sync/budget_unit", json={"intervalSeconds": 3600})).status_code == 403


async def test_post_kind_validation_and_credential_errors(client, make_user, auth_as, sm, api_settings, session_password):
    api_settings(erp_sync_userid="", erp_sync_password="")  # 서비스 계정 없음
    session_password(None)
    uid = await make_user("es-admin2", "admin")
    auth_as(uid)
    assert (await client.post("/admin/erp-sync/nope")).status_code == 422
    resp = await client.post("/admin/erp-sync/project")
    assert resp.status_code == 409 and "자격증명" in resp.json()["error"]
    # 로컬 계정 + 세션 비밀번호 있어도 org_unit 은 400.
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        u.password_hash = "x"
        await s.commit()
    session_password("pw")
    resp = await client.post("/admin/erp-sync/org_unit")
    assert resp.status_code == 400 and "실제 ERP 계정" in resp.json()["error"]
    # all 도 자격증명 불가면 전체 거절(부분 실행 없음) — 첫 kind(budget_unit) 기준 409.
    assert (await client.post("/admin/erp-sync/all")).status_code == 409
    assert await _rows(sm) == []


async def test_local_admin_without_service_account(client, make_user, auth_as, sm, api_settings, session_password):
    """로컬 admin(세션 비밀번호 1111 캐시됨) + 서비스 계정 없음 → credentialSource null, POST 409 안내."""
    api_settings(erp_sync_userid="", erp_sync_password="")
    session_password("1111")
    uid = await make_user("es-local-admin", "admin")
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        u.password_hash = "bcrypt-hash"
        await s.commit()
    auth_as(uid)
    body = (await client.get("/admin/erp-sync")).json()
    assert body["credentialSource"] is None
    resp = await client.post("/admin/erp-sync/budget_unit")
    assert resp.status_code == 409 and "서비스 계정" in resp.json()["error"]
    assert await _rows(sm) == []  # 실행 시도 자체가 없다


async def test_local_admin_with_service_account_uses_service(client, make_user, auth_as, sm, monkeypatch, api_settings, session_password):
    """로컬 admin + 서비스 계정 → credentialSource 'service', 실제 sync 는 서비스 계정으로 호출."""
    api_settings()
    session_password("1111")
    uid = await make_user("es-local-admin2", "admin")
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        u.password_hash = "bcrypt-hash"
        await s.commit()
    auth_as(uid)
    assert (await client.get("/admin/erp-sync")).json()["credentialSource"] == "service"
    seen: dict = {}

    async def _fake(kind, userid, password, browser_factory, sessionmaker):
        seen["cred"] = (userid, password)
        return {"count": 1, "syncedAt": "x", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake)
    assert (await client.post("/admin/erp-sync/partner")).status_code == 202
    await _drain_tasks()
    assert seen["cred"] == ("svc", "svc-pw")  # 세션 비밀번호 1111 은 쓰이지 않는다


async def test_post_kind_busy_returns_409(client, make_user, auth_as, api_settings, session_password):
    api_settings()
    session_password("pw")
    auth_as(await make_user("es-admin3", "admin"))
    sem = fastapi_app.state.catalog_sync_semaphore
    await sem.acquire()
    try:
        resp = await client.post("/admin/erp-sync/partner")
        assert resp.status_code == 409 and "진행 중" in resp.json()["error"]
        assert (await client.post("/admin/erp-sync/all")).status_code == 409
    finally:
        sem.release()


async def test_post_kind_service_fallback_runs_and_records(client, make_user, auth_as, sm, monkeypatch, api_settings, session_password):
    api_settings()
    session_password(None)  # 세션 비밀번호 없음 → 서비스 계정 폴백
    uid = await make_user("es-admin4", "admin")
    auth_as(uid)
    seen: dict = {}

    async def _fake(kind, userid, password, browser_factory, sessionmaker):
        seen["cred"] = (userid, password)
        return {"count": 11, "syncedAt": "2026-09-02T00:00:00+00:00", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake)
    resp = await client.post("/admin/erp-sync/budget_unit")
    assert resp.status_code == 202 and resp.json() == {"started": True}
    await _drain_tasks()
    assert seen["cred"] == ("svc", "svc-pw")
    body = (await client.get("/admin/erp-sync")).json()
    item = next(i for i in body["items"] if i["kind"] == "budget_unit")
    assert item["running"] is False
    assert item["lastRun"]["status"] == "succeeded" and item["lastRun"]["count"] == 11
    assert item["lastRun"]["trigger"] == "manual" and item["lastRun"]["actorName"] == "es-admin4"
    assert item["lastSuccessAt"] == item["lastRun"]["finishedAt"]
    # 기존 /me/catalog/sync-status 도 같은 RAM 상태를 본다(응답 불변).
    st = (await client.get("/me/catalog/sync-status?kind=budget_unit")).json()
    assert st["running"] is False and st["error"] is None and st["count"] == 0


async def test_post_all_runs_sequentially(client, make_user, auth_as, sm, monkeypatch, api_settings, session_password):
    api_settings()
    session_password("sess")
    uid = await make_user("es-admin5", "admin")
    auth_as(uid)
    order: list[tuple[str, str]] = []

    async def _fake(kind, userid, password, browser_factory, sessionmaker):
        order.append((kind, userid))
        return {"count": 1, "syncedAt": "x", "via": "api"}

    monkeypatch.setattr(erp_sync, "sync_catalog", _fake)
    resp = await client.post("/admin/erp-sync/all")
    assert resp.status_code == 202
    assert resp.json() == {"started": True, "kinds": ["budget_unit", "project", "partner", "org_unit"]}
    await _drain_tasks()
    # 세션 사용자(password_hash None)라 org_unit 까지 세션 계정으로.
    assert order == [(k, "es-admin5") for k in ("budget_unit", "project", "partner", "org_unit")]
    rows = await _rows(sm)
    assert [r.kind for r in rows] == ["budget_unit", "project", "partner", "org_unit"]
    assert all(r.status == "succeeded" and r.trigger == "manual" and r.actor_user_id == uid for r in rows)
    assert fastapi_app.state.catalog_sync_semaphore.locked() is False

    runs = (await client.get("/admin/erp-sync/runs?limit=2")).json()["items"]
    assert [r["kind"] for r in runs] == ["org_unit", "partner"]  # 최신순
    only = (await client.get("/admin/erp-sync/runs?kind=project")).json()["items"]
    assert len(only) == 1 and only[0]["kind"] == "project" and only[0]["actorName"] == "es-admin5"
    assert (await client.get("/admin/erp-sync/runs?kind=nope")).status_code == 422
    assert (await client.get("/admin/erp-sync/runs?limit=0")).status_code == 422


async def test_legacy_me_catalog_sync_writes_history(client, make_user, auth_as, sm, monkeypatch):
    """기존 POST /me/catalog/sync 도 공용 러너를 타서 이력이 남는다(응답은 불변)."""
    from app.routers import me_codes

    uid = await make_user("es-legacy", "user")
    auth_as(uid)
    monkeypatch.setattr(me_codes, "_omnisol_password", lambda request: "pw")
    monkeypatch.setattr(erp_sync, "sync_catalog", _ok_sync(4))
    resp = await client.post("/me/catalog/sync", json={"kind": "partner"})
    assert resp.status_code == 202 and resp.json() == {"started": True}
    await _drain_tasks()
    (row,) = await _rows(sm)
    assert row.kind == "partner" and row.trigger == "manual" and row.status == "succeeded"
    assert row.count == 4 and row.actor_user_id == uid
    st = (await client.get("/me/catalog/sync-status?kind=partner")).json()
    assert st["running"] is False and st["lastSyncedAt"] and st["error"] is None
