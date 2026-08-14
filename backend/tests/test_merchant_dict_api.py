"""가맹점 사전 CRUD API — /me/merchant-dict (조회 전원 / 편집 관리자).

DB(merchant_dict_rules) 기반 하이브리드 사전. 조회는 세션, 편집은 admin+ 게이트.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_list_requires_session_only(client, make_user, auth_as):
    uid = await make_user("md-viewer", "user")
    auth_as(uid)
    r = await client.get("/me/merchant-dict")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)


async def test_create_forbidden_for_non_admin(client, make_user, auth_as):
    uid = await make_user("md-user", "user")
    auth_as(uid)
    r = await client.post("/me/merchant-dict", json={"keywords": ["kw"], "category": "테스트"})
    assert r.status_code == 403


async def test_admin_crud_roundtrip(client, make_user, auth_as):
    uid = await make_user("md-admin", "admin")
    auth_as(uid)
    # 생성 — 키워드는 소문자 정규화.
    r = await client.post(
        "/me/merchant-dict",
        json={"keywords": ["  TollX ", "주차X"], "category": "테스트주차", "sortOrder": 500},
    )
    assert r.status_code == 201
    rule = r.json()
    assert rule["keywords"] == ["tollx", "주차x"] and rule["category"] == "테스트주차"
    rid = rule["id"]

    # 수정 — strong·acct 반영.
    r = await client.patch(
        f"/me/merchant-dict/{rid}",
        json={"keywords": ["주차x"], "category": "테스트주차2", "acct": "여비교통비-국내출장", "strong": True},
    )
    assert r.status_code == 200
    assert r.json()["strong"] is True and r.json()["acct"] == "여비교통비-국내출장"

    # 삭제.
    r = await client.delete(f"/me/merchant-dict/{rid}")
    assert r.status_code == 204
    # 삭제 후 조회 목록에서 사라짐.
    got = await client.get("/me/merchant-dict")
    assert all(it["id"] != rid for it in got.json()["items"])


async def test_create_rejects_empty_keywords(client, make_user, auth_as):
    uid = await make_user("md-admin2", "admin")
    auth_as(uid)
    r = await client.post("/me/merchant-dict", json={"keywords": ["  "], "category": "x"})
    assert r.status_code == 422


async def test_delete_unknown_id_404(client, make_user, auth_as):
    uid = await make_user("md-admin3", "admin")
    auth_as(uid)
    import uuid

    r = await client.delete(f"/me/merchant-dict/{uuid.uuid4()}")
    assert r.status_code == 404
