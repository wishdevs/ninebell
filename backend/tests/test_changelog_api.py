"""변경사항(릴리스 노트) CRUD API — /changelog (조회 전원 / 편집 관리자).

일반 사용자는 released 만 보고, draft 는 관리자 전용이다. version 중복은 409.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _create(client, **overrides) -> dict:
    payload = {
        "version": overrides.pop("version", "v0.0.1"),
        "title": overrides.pop("title", "테스트 릴리스"),
        "bodyMd": overrides.pop("bodyMd", "### 추가\n- 무언가"),
        **overrides,
    }
    r = await client.post("/changelog", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def test_list_requires_session_only(client, make_user, auth_as):
    uid = await make_user("cl-viewer", "user")
    auth_as(uid)
    r = await client.get("/changelog")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["items"], list) and "total" in body


async def test_create_forbidden_for_non_admin(client, make_user, auth_as):
    uid = await make_user("cl-user", "user")
    auth_as(uid)
    r = await client.post("/changelog", json={"version": "v9", "title": "t", "bodyMd": "b"})
    assert r.status_code == 403


async def test_admin_crud_roundtrip(client, make_user, auth_as):
    uid = await make_user("cl-admin", "admin")
    auth_as(uid)

    entry = await _create(client, version="v1.0.0", title="첫 릴리스", releasedAt="2026-07-01")
    assert entry["status"] == "released"
    assert entry["releasedAt"] == "2026-07-01"
    eid = entry["id"]

    # 단건 조회.
    got = await client.get(f"/changelog/{eid}")
    assert got.status_code == 200 and got.json()["title"] == "첫 릴리스"

    # 전체 교체 수정.
    r = await client.patch(
        f"/changelog/{eid}",
        json={
            "version": "v1.0.1",
            "title": "수정된 릴리스",
            "bodyMd": "### 수정\n- 고침",
            "status": "draft",
        },
    )
    assert r.status_code == 200
    assert r.json()["version"] == "v1.0.1" and r.json()["status"] == "draft"

    # 삭제.
    assert (await client.delete(f"/changelog/{eid}")).status_code == 204
    listed = await client.get("/changelog")
    assert all(it["id"] != eid for it in listed.json()["items"])


async def test_draft_hidden_from_normal_user(client, make_user, auth_as):
    admin = await make_user("cl-admin2", "admin")
    auth_as(admin)
    draft = await _create(client, version="v2.0.0-draft", status="draft")
    public = await _create(client, version="v2.0.0", status="released")

    viewer = await make_user("cl-viewer2", "user")
    auth_as(viewer)
    ids = {it["id"] for it in (await client.get("/changelog")).json()["items"]}
    assert public["id"] in ids
    assert draft["id"] not in ids
    # 딥링크로도 존재를 숨긴다.
    assert (await client.get(f"/changelog/{draft['id']}")).status_code == 404


async def test_list_sorted_by_released_at_desc(client, make_user, auth_as):
    uid = await make_user("cl-admin3", "admin")
    auth_as(uid)
    await _create(client, version="v3.0.0", releasedAt="2026-01-01")
    await _create(client, version="v3.1.0", releasedAt="2026-06-01")

    items = (await client.get("/changelog?q=v3.")).json()["items"]
    assert [it["version"] for it in items] == ["v3.1.0", "v3.0.0"]


async def test_major_fix_flag_and_filter(client, make_user, auth_as):
    uid = await make_user("cl-admin-major", "admin")
    auth_as(uid)
    major = await _create(client, version="v7.0.0", hasMajorFix=True, releasedAt="2026-03-01")
    minor = await _create(client, version="v7.1.0", releasedAt="2026-03-02")
    assert major["hasMajorFix"] is True
    assert minor["hasMajorFix"] is False  # 생략 시 기본 False

    only_major = (await client.get("/changelog?q=v7.&hasMajorFix=true")).json()["items"]
    assert [it["version"] for it in only_major] == ["v7.0.0"]

    only_minor = (await client.get("/changelog?q=v7.&hasMajorFix=false")).json()["items"]
    assert [it["version"] for it in only_minor] == ["v7.1.0"]

    # 파라미터 생략 시 필터 없음.
    assert len((await client.get("/changelog?q=v7.")).json()["items"]) == 2

    # PATCH 로 해제 가능(전체 교체 규약 — 생략하면 False 로 돌아간다).
    r = await client.patch(
        f"/changelog/{major['id']}",
        json={"version": "v7.0.0", "title": "t", "bodyMd": "b"},
    )
    assert r.status_code == 200 and r.json()["hasMajorFix"] is False


async def test_released_at_is_a_calendar_date_not_an_instant(client, make_user, auth_as):
    """보낸 날짜가 그대로 돌아오고, 다시 저장해도 밀리지 않는다.

    회귀: timestamptz 로 저장하던 시절 KST 자정이 UTC 로 환산돼 '2026-07-28' → '2026-07-27'
    로 하루 밀렸고, 수정 다이얼로그가 그 값을 되보내며 저장할 때마다 하루씩 뒤로 걸어갔다.
    """
    uid = await make_user("cl-admin-date", "admin")
    auth_as(uid)
    entry = await _create(client, version="v8.0.0", releasedAt="2026-07-28")
    assert entry["releasedAt"] == "2026-07-28"  # 시각·오프셋 없이 날짜 그대로

    # 받은 값을 그대로 되보내는 왕복을 3번 — 하루도 밀리지 않아야 한다.
    current = entry
    for _ in range(3):
        r = await client.patch(
            f"/changelog/{entry['id']}",
            json={
                "version": current["version"],
                "title": current["title"],
                "bodyMd": current["bodyMd"],
                "releasedAt": current["releasedAt"],
            },
        )
        assert r.status_code == 200
        current = r.json()
    assert current["releasedAt"] == "2026-07-28"


async def test_duplicate_version_conflicts(client, make_user, auth_as):
    uid = await make_user("cl-admin4", "admin")
    auth_as(uid)
    await _create(client, version="v4.0.0")
    r = await client.post("/changelog", json={"version": "v4.0.0", "title": "t", "bodyMd": "b"})
    assert r.status_code == 409


async def test_create_rejects_empty_body(client, make_user, auth_as):
    uid = await make_user("cl-admin5", "admin")
    auth_as(uid)
    r = await client.post("/changelog", json={"version": "v5.0.0", "title": "t", "bodyMd": ""})
    assert r.status_code == 422


async def test_unknown_id_404(client, make_user, auth_as):
    uid = await make_user("cl-admin6", "admin")
    auth_as(uid)
    assert (await client.delete(f"/changelog/{uuid.uuid4()}")).status_code == 404
