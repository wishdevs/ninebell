"""내 즐겨찾기 ERP 코드 + 공용 카탈로그 + 동기화 트리거 라우터 테스트.

- favorites: CRUD 왕복, 중복 POST 멱등, 남의 것 DELETE 404, reorder, kind 필터.
- catalog: q 검색, dept 기본/all 필터, 페이지네이션, 봉투 {items,total,syncedAt}.
- sync 가드: 자격증명 없음 409, 세마포어 점유 409.
- sync_catalog 스모크: 진입 체인·덤프 몽키패치로 upsert/stale 삭제 검증.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import app.routers.me_codes as me_codes
import app.services.code_sync as code_sync
from app.models import ErpCodeCatalog, User


async def _seed_catalog(sm, rows: list[dict]) -> None:
    async with sm() as s:
        for r in rows:
            s.add(ErpCodeCatalog(**r))
        await s.commit()


async def _set_department(sm, user_id, dept: str) -> None:
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
        u.department = dept
        await s.commit()


# ── 즐겨찾기 CRUD ─────────────────────────────────────────────────────────────
async def test_favorite_crud_roundtrip(client, make_user, auth_as):
    uid = await make_user("fav-user", "user")
    auth_as(uid)

    resp = await client.get("/me/favorites?kind=budget_unit")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}

    created = await client.post(
        "/me/favorites",
        json={"kind": "budget_unit", "code": "BG1", "name": "경영본부", "extra": {"deptNm": "경영"}},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["kind"] == "budget_unit"
    assert item["code"] == "BG1"
    assert item["extra"] == {"deptNm": "경영"}
    fav_id = item["id"]

    listed = await client.get("/me/favorites?kind=budget_unit")
    assert [i["code"] for i in listed.json()["items"]] == ["BG1"]

    deleted = await client.delete(f"/me/favorites/{fav_id}")
    assert deleted.status_code == 204
    assert (await client.get("/me/favorites?kind=budget_unit")).json() == {"items": []}


async def test_favorite_duplicate_is_idempotent(client, make_user, auth_as):
    uid = await make_user("fav-dup", "user")
    auth_as(uid)
    first = await client.post(
        "/me/favorites", json={"kind": "project", "code": "P1", "name": "프로젝트1"}
    )
    assert first.status_code == 201
    second = await client.post(
        "/me/favorites", json={"kind": "project", "code": "P1", "name": "프로젝트1"}
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    # 중복이 실제 행을 늘리지 않는다.
    assert len((await client.get("/me/favorites?kind=project")).json()["items"]) == 1


async def test_delete_others_favorite_returns_404(client, make_user, auth_as):
    owner = await make_user("fav-owner", "user")
    other = await make_user("fav-other", "user")
    auth_as(owner)
    created = await client.post(
        "/me/favorites", json={"kind": "project", "code": "PX", "name": "x"}
    )
    fav_id = created.json()["id"]

    auth_as(other)
    resp = await client.delete(f"/me/favorites/{fav_id}")
    assert resp.status_code == 404
    # 소유자 것은 그대로 남아 있다.
    auth_as(owner)
    assert len((await client.get("/me/favorites?kind=project")).json()["items"]) == 1


async def test_favorite_reorder(client, make_user, auth_as):
    uid = await make_user("fav-reorder", "user")
    auth_as(uid)
    ids = []
    for code in ("A", "B", "C"):
        r = await client.post(
            "/me/favorites", json={"kind": "budget_unit", "code": code, "name": code}
        )
        ids.append(r.json()["id"])

    # C, A, B 순으로 재배치.
    reordered = await client.post(
        "/me/favorites/reorder",
        json={"kind": "budget_unit", "orderedIds": [ids[2], ids[0], ids[1]]},
    )
    assert reordered.status_code == 200
    assert [i["code"] for i in reordered.json()["items"]] == ["C", "A", "B"]


async def test_favorite_kind_filter(client, make_user, auth_as):
    uid = await make_user("fav-kind", "user")
    auth_as(uid)
    await client.post("/me/favorites", json={"kind": "budget_unit", "code": "BG", "name": "b"})
    await client.post("/me/favorites", json={"kind": "project", "code": "PJ", "name": "p"})

    bg = await client.get("/me/favorites?kind=budget_unit")
    assert [i["code"] for i in bg.json()["items"]] == ["BG"]
    pj = await client.get("/me/favorites?kind=project")
    assert [i["code"] for i in pj.json()["items"]] == ["PJ"]


# ── 카탈로그 조회 ────────────────────────────────────────────────────────────
async def test_catalog_query_and_envelope(client, make_user, auth_as, sm):
    uid = await make_user("cat-user", "user")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    await _seed_catalog(
        sm,
        [
            {"kind": "project", "dept": "", "code": "P100", "name": "알파 프로젝트", "synced_at": now},
            {"kind": "project", "dept": "", "code": "P200", "name": "베타 프로젝트", "synced_at": now},
        ],
    )
    resp = await client.get("/me/catalog?kind=project")
    body = resp.json()
    assert body["total"] == 2
    assert body["syncedAt"] is not None
    assert {i["code"] for i in body["items"]} == {"P100", "P200"}

    # q 는 name/code ILIKE.
    filtered = await client.get("/me/catalog?kind=project&q=알파")
    assert [i["code"] for i in filtered.json()["items"]] == ["P100"]
    by_code = await client.get("/me/catalog?kind=project&q=P200")
    assert [i["code"] for i in by_code.json()["items"]] == ["P200"]


async def test_catalog_dept_default_and_all(client, make_user, auth_as, sm):
    uid = await make_user("cat-dept", "user")
    await _set_department(sm, uid, "인사/기획팀")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    await _seed_catalog(
        sm,
        [
            {"kind": "budget_unit", "dept": "인사/기획팀", "code": "B1", "name": "인사예산", "synced_at": now},
            {"kind": "budget_unit", "dept": "영업팀", "code": "B2", "name": "영업예산", "synced_at": now},
        ],
    )
    # 기본 = 사용자 부서 스코프.
    default = await client.get("/me/catalog?kind=budget_unit")
    assert [i["code"] for i in default.json()["items"]] == ["B1"]
    # dept=all → 필터 해제.
    all_dept = await client.get("/me/catalog?kind=budget_unit&dept=all")
    assert {i["code"] for i in all_dept.json()["items"]} == {"B1", "B2"}
    # 명시 dept.
    explicit = await client.get("/me/catalog?kind=budget_unit&dept=영업팀")
    assert [i["code"] for i in explicit.json()["items"]] == ["B2"]


async def test_catalog_limit_offset(client, make_user, auth_as, sm):
    uid = await make_user("cat-page", "user")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    await _seed_catalog(
        sm,
        [
            {"kind": "project", "dept": "", "code": f"P{i:02d}", "name": f"proj{i:02d}", "synced_at": now}
            for i in range(5)
        ],
    )
    page1 = await client.get("/me/catalog?kind=project&limit=2&offset=0")
    assert page1.json()["total"] == 5
    assert len(page1.json()["items"]) == 2
    page3 = await client.get("/me/catalog?kind=project&limit=2&offset=4")
    assert len(page3.json()["items"]) == 1


async def test_catalog_empty_syncedat_null(client, make_user, auth_as):
    uid = await make_user("cat-empty", "user")
    auth_as(uid)
    resp = await client.get("/me/catalog?kind=project")
    assert resp.json() == {"items": [], "total": 0, "syncedAt": None}


# ── 동기화 가드 ──────────────────────────────────────────────────────────────
async def test_sync_without_credentials_returns_409(client, make_user, auth_as):
    uid = await make_user("sync-nocred", "user")
    auth_as(uid)
    # cred_cache 미존재(lifespan 미실행) → 비밀번호 None → 409.
    resp = await client.post("/me/catalog/sync", json={"kind": "project"})
    assert resp.status_code == 409
    assert "자격증명" in resp.json()["error"]


async def test_sync_semaphore_held_returns_409(client, make_user, auth_as, monkeypatch):
    uid = await make_user("sync-busy", "user")
    auth_as(uid)
    # 자격증명은 있다고 가정(비밀번호 조회 몽키패치).
    monkeypatch.setattr(me_codes, "_omnisol_password", lambda request: "pw")
    from app.main import app as fastapi_app

    sem = fastapi_app.state.catalog_sync_semaphore
    await sem.acquire()  # 이미 진행 중 상태를 만든다.
    try:
        resp = await client.post("/me/catalog/sync", json={"kind": "project"})
        assert resp.status_code == 409
        assert "진행 중" in resp.json()["error"]
    finally:
        sem.release()


# ── sync_catalog 스모크(브라우저·진입 몽키패치) ─────────────────────────────────
class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def new_page(self, viewport=None):  # noqa: ANN001
        return object()

    async def close(self) -> None:
        self.closed = True


async def test_sync_catalog_budget_units_upsert_and_stale_delete(sm, monkeypatch):
    # 진입 체인은 no-op, 덤프는 가짜 2행. 기존 stale 1행은 삭제돼야 한다.
    await _seed_catalog(
        sm,
        [
            {"kind": "budget_unit", "dept": "인사/기획팀", "code": "OLD", "name": "옛예산",
             "synced_at": datetime.now(timezone.utc)},
        ],
    )

    async def _noop_chain(page, userid, password):  # noqa: ANN001
        return None

    async def _fake_dump(page):  # noqa: ANN001
        return [
            {"code": "B1", "name": "예산1", "deptNm": "인사/기획팀"},
            {"code": "B2", "name": "예산2", "deptNm": "인사/기획팀"},
        ]

    browser = _FakeBrowser()

    async def _factory():
        return browser

    monkeypatch.setattr(code_sync, "_run_entry_chain", _noop_chain)
    monkeypatch.setattr(code_sync.steps, "dump_budget_units", _fake_dump)

    result = await code_sync.sync_catalog("budget_unit", "u", "p", _factory, sm)
    assert result["count"] == 2
    assert browser.closed is True

    async with sm() as s:
        rows = (
            (await s.execute(select(ErpCodeCatalog).where(ErpCodeCatalog.kind == "budget_unit")))
            .scalars()
            .all()
        )
    codes = {r.code for r in rows}
    assert codes == {"B1", "B2"}  # OLD 는 stale 삭제됨.
