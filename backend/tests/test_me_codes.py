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
from app.models import CardSeedSelection, ErpCodeCatalog, User


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


async def test_favorite_created_is_not_default(client, make_user, auth_as):
    uid = await make_user("fav-default-init", "user")
    auth_as(uid)
    created = await client.post(
        "/me/favorites", json={"kind": "project", "code": "P1", "name": "프로젝트1"}
    )
    assert created.json()["isDefault"] is False


async def test_set_default_is_single_per_kind(client, make_user, auth_as):
    """(user,kind) 당 기본은 1개 — 두 번째 지정 시 첫 번째가 자동 해제된다."""
    uid = await make_user("fav-default", "user")
    auth_as(uid)
    ids = []
    for code in ("P1", "P2"):
        r = await client.post("/me/favorites", json={"kind": "project", "code": code, "name": code})
        ids.append(r.json()["id"])

    first = await client.post(f"/me/favorites/{ids[0]}/default")
    assert first.status_code == 200
    assert first.json()["isDefault"] is True

    # 두 번째 지정 → 첫 번째 해제.
    await client.post(f"/me/favorites/{ids[1]}/default")
    listed = {i["id"]: i["isDefault"] for i in (await client.get("/me/favorites?kind=project")).json()["items"]}
    assert listed[ids[0]] is False
    assert listed[ids[1]] is True


async def test_set_default_is_scoped_per_kind(client, make_user, auth_as):
    """기본 지정은 kind 별로 독립 — 프로젝트 기본이 예산단위 기본을 건드리지 않는다."""
    uid = await make_user("fav-default-kind", "user")
    auth_as(uid)
    bg = await client.post("/me/favorites", json={"kind": "budget_unit", "code": "B1", "name": "b"})
    pj = await client.post("/me/favorites", json={"kind": "project", "code": "P1", "name": "p"})
    await client.post(f"/me/favorites/{bg.json()['id']}/default")
    await client.post(f"/me/favorites/{pj.json()['id']}/default")
    bg_items = {i["id"]: i["isDefault"] for i in (await client.get("/me/favorites?kind=budget_unit")).json()["items"]}
    assert bg_items[bg.json()["id"]] is True


async def test_set_default_others_favorite_returns_404(client, make_user, auth_as):
    owner = await make_user("def-owner", "user")
    other = await make_user("def-other", "user")
    auth_as(owner)
    created = await client.post(
        "/me/favorites", json={"kind": "project", "code": "PX", "name": "x"}
    )
    fav_id = created.json()["id"]

    auth_as(other)
    resp = await client.post(f"/me/favorites/{fav_id}/default")
    assert resp.status_code == 404
    # 소유자 것은 기본이 지정되지 않았다.
    auth_as(owner)
    items = (await client.get("/me/favorites?kind=project")).json()["items"]
    assert items[0]["isDefault"] is False


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


async def test_card_seed_list_and_search(client, make_user, auth_as, sm):
    """전사 seed 목록 — 빈도순 + total 반환 + 가맹점 q 검색(공용 데이터, user 무관)."""
    uid = await make_user("seed-user", "user")
    auth_as(uid)
    async with sm() as s:
        s.add(CardSeedSelection(
            norm_merchant="맘스터치상대원점", merchant="맘스터치 상대원점",
            acct_code="81100", acct_name="복리후생비-석식", note="직원 야근식대",
            count=562, dominance=0.93, last_year=2025,
        ))
        s.add(CardSeedSelection(
            norm_merchant="지에스25성남", merchant="지에스25 성남",
            acct_code="81100", acct_name="복리후생비-석식", note="야근식대",
            count=745, dominance=0.79, last_year=2025,
        ))
        await s.commit()

    body = (await client.get("/me/card-learning/seed")).json()
    assert body["total"] == 2
    # 빈도순(745 먼저).
    assert [i["merchant"] for i in body["items"]] == ["지에스25 성남", "맘스터치 상대원점"]
    assert body["items"][0]["acctName"] == "복리후생비-석식"

    # q 는 가맹점명 ILIKE. total 은 필터 적용 후 건수(페이지 계산용).
    filtered = (await client.get("/me/card-learning/seed?q=맘스터치")).json()
    assert [i["merchant"] for i in filtered["items"]] == ["맘스터치 상대원점"]
    assert filtered["total"] == 1

    # 페이지네이션(limit/offset) — 빈도순 2페이지.
    page1 = (await client.get("/me/card-learning/seed?limit=1&offset=0")).json()
    page2 = (await client.get("/me/card-learning/seed?limit=1&offset=1")).json()
    assert page1["total"] == 2 and page2["total"] == 2
    assert [i["merchant"] for i in page1["items"]] == ["지에스25 성남"]
    assert [i["merchant"] for i in page2["items"]] == ["맘스터치 상대원점"]


async def test_catalog_project_q_covers_wbs_extra(client, make_user, auth_as, sm):
    """프로젝트 q 는 name/code 외에 extra(wbsNm/loc/pjtNo)도 부분 매칭한다(파이썬 필터)."""
    uid = await make_user("cat-proj-wbs", "user")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    await _seed_catalog(
        sm,
        [
            {
                "kind": "project", "dept": "", "code": "PJ100|W1", "name": "알파 프로젝트",
                "extra": {"pjtNo": "PJ100", "wbsNo": "W1", "wbsNm": "정비 요소", "loc": "부산"},
                "synced_at": now,
            },
            {
                "kind": "project", "dept": "", "code": "PJ200|W9", "name": "베타 프로젝트",
                "extra": {"pjtNo": "PJ200", "wbsNo": "W9", "wbsNm": "설계 요소", "loc": "서울"},
                "synced_at": now,
            },
        ],
    )
    # WBS요소명 매칭.
    by_wbsnm = await client.get("/me/catalog?kind=project&q=정비")
    assert [i["code"] for i in by_wbsnm.json()["items"]] == ["PJ100|W1"]
    # 위치(loc) 매칭.
    by_loc = await client.get("/me/catalog?kind=project&q=서울")
    assert [i["code"] for i in by_loc.json()["items"]] == ["PJ200|W9"]
    # 프로젝트번호(pjtNo) 매칭 + extra 가 응답에 실린다.
    by_pjtno = await client.get("/me/catalog?kind=project&q=PJ100")
    body = by_pjtno.json()
    assert [i["code"] for i in body["items"]] == ["PJ100|W1"]
    assert body["items"][0]["extra"]["wbsNm"] == "정비 요소"


async def test_catalog_dept_default_and_all(client, make_user, auth_as, sm):
    """예산단위 '내 부서' 필터 = dept 컬럼이 아니라 **이름 정규화 매칭**.

    소속 '인사/기획팀' ↔ 예산단위명 '인사기획팀'(슬래시 없음)이 매칭돼야 한다(실 ERP 사례).
    """
    uid = await make_user("cat-dept", "user")
    await _set_department(sm, uid, "인사/기획팀")
    auth_as(uid)
    now = datetime.now(timezone.utc)
    await _seed_catalog(
        sm,
        [
            {"kind": "budget_unit", "dept": "", "code": "B1", "name": "인사기획팀", "synced_at": now},
            {"kind": "budget_unit", "dept": "", "code": "B2", "name": "영업 본부", "synced_at": now},
        ],
    )
    # 기본 = 소속부서 정규화 매칭('인사/기획팀' → '인사기획팀').
    default = await client.get("/me/catalog?kind=budget_unit")
    assert [i["code"] for i in default.json()["items"]] == ["B1"]
    # dept=all → 필터 해제(전사 전체).
    all_dept = await client.get("/me/catalog?kind=budget_unit&dept=all")
    assert {i["code"] for i in all_dept.json()["items"]} == {"B1", "B2"}
    # 명시 dept → 그 부서명으로 정규화 매칭('영업본부' ↔ '영업 본부').
    explicit = await client.get("/me/catalog?kind=budget_unit&dept=영업본부")
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


async def test_sync_catalog_projects_wbs_rows(sm, monkeypatch):
    """프로젝트 동기화 — WBS 행 단위(code=PJT_NO|WBS_NO)로 upsert + extra 보존."""

    async def _noop_chain(page, userid, password):  # noqa: ANN001
        return None

    async def _fake_scroll(page):  # noqa: ANN001
        rows = [
            {"code": "PJ1|W1", "name": "알파", "pjtNo": "PJ1", "wbsNo": "W1",
             "wbsNm": "정비", "loc": "부산", "useYn": "Y", "partnerNm": "가나상사"},
            {"code": "PJ1|W2", "name": "알파", "pjtNo": "PJ1", "wbsNo": "W2",
             "wbsNm": "설계", "loc": "서울", "useYn": "Y", "partnerNm": "가나상사"},
        ]
        return rows, 2, 2  # (rows, server_total, raw_loaded) — raw_loaded>=total 이라 스윕 생략.

    browser = _FakeBrowser()

    async def _factory():
        return browser

    monkeypatch.setattr(code_sync, "_run_entry_chain", _noop_chain)
    monkeypatch.setattr(code_sync.steps, "dump_projects_scroll", _fake_scroll)

    result = await code_sync.sync_catalog("project", "u", "p", _factory, sm)
    assert result["count"] == 2

    async with sm() as s:
        rows = (
            (await s.execute(select(ErpCodeCatalog).where(ErpCodeCatalog.kind == "project")))
            .scalars()
            .all()
        )
    by_code = {r.code: r for r in rows}
    assert set(by_code) == {"PJ1|W1", "PJ1|W2"}  # 같은 PJT_NO 도 WBS_NO 로 분리 유지.
    assert by_code["PJ1|W1"].name == "알파"
    assert by_code["PJ1|W1"].extra["wbsNm"] == "정비"
    assert by_code["PJ1|W1"].extra["loc"] == "부산"
    assert by_code["PJ1|W1"].extra["pjtNo"] == "PJ1"


async def test_default_favorite_toggles_off_on_second_click(client, make_user, auth_as):
    """기본지정을 다시 클릭하면 해제된다(토글, 2026-07-04)."""
    uid = await make_user("u-toggle", "user")
    auth_as(uid)
    r = await client.post(
        "/me/favorites",
        json={"kind": "project", "code": "800|800", "name": "판매관리비", "extra": {"wbsNo": "800"}},
    )
    fav_id = r.json()["id"]
    # 지정 → isDefault true
    r1 = await client.post(f"/me/favorites/{fav_id}/default")
    assert r1.status_code == 200 and r1.json()["isDefault"] is True
    # 다시 클릭 → 해제
    r2 = await client.post(f"/me/favorites/{fav_id}/default")
    assert r2.status_code == 200 and r2.json()["isDefault"] is False
    # 목록에서도 해제 확인
    favs = (await client.get("/me/favorites", params={"kind": "project"})).json()["items"]
    assert all(not f["isDefault"] for f in favs)


async def test_card_learning_debug_lists_recorded(client, make_user, auth_as, sm):
    """개입 학습 디버그 조회 — record_selections 로 쌓은 항목을 빈도순으로 반환."""
    from app.services import card_learning

    uid = await make_user("u-learn", "user")
    auth_as(uid)
    # 같은 가맹점 2회(count=2) + 다른 가맹점 1회.
    entry = {
        "merchant": "네이버파이낸셜㈜",
        "budget": {"code": "2006|1|2", "name": "인사기획팀", "bgacctNm": "(판)소모품비"},
        "project": {"code": "800|800", "name": "판매관리비", "wbsNo": "800"},
        "note": "소모품",
    }
    await card_learning.record_selections(str(uid), [entry])
    await card_learning.record_selections(str(uid), [entry])  # 재확정 → count 2
    await card_learning.record_selections(str(uid), [{"merchant": "쿠팡", "budget": {"code": "x", "name": "y"}}])

    r = await client.get("/me/card-learning")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    top = items[0]  # 빈도순 → 네이버(count=2) 먼저
    assert top["merchant"] == "네이버파이낸셜㈜" and top["count"] == 2
    assert top["budget"]["bgacctNm"] == "(판)소모품비" and top["project"]["wbsNo"] == "800"


async def test_card_learning_retrieve_matches_normalized_merchant(sm, make_user):
    """정규화 매칭 — '네이버파이낸셜㈜' 저장분이 '네이버파이낸셜(주)' 조회로 잡힌다."""
    from app.services import card_learning

    uid = await make_user("u-learn2", "user")
    await card_learning.record_selections(
        str(uid), [{"merchant": "네이버파이낸셜㈜", "budget": {"code": "b", "name": "n"}}]
    )
    hits = await card_learning.retrieve_for_merchants(str(uid), ["네이버파이낸셜(주)"])
    assert card_learning.norm_merchant("네이버파이낸셜(주)") in hits
