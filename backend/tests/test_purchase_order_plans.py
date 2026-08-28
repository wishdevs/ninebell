"""구매발주 계획서 보관 — record_plan 서비스 + /purchase-order/plans 조회 API.

sm 픽스처가 app.db.init_engine 으로 전역 엔진을 세팅하므로 서비스의 get_sessionmaker() 가
테스트 SQLite 를 그대로 쓴다(별도 monkeypatch 불필요).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import PurchaseOrderPlan
from app.services import purchase_order_plans as svc

pytestmark = pytest.mark.asyncio


def _plan(**over) -> dict:
    base = {
        "project": {"code": "2297", "name": "CX85-137"},
        "wbs": "PO-2026-07-4136",
        "units": [
            {
                "seq": 1,
                "purchaseReason": "CX85-137 · 12CH PROCESS BUFFER",
                "dueDate": "2026-09-01",
                "modules": [{"itemCode": "SET-001", "name": "외주조립-BUFFER", "spec": ""}],
                "vendorGroups": [
                    {"vendorClass": "가공품", "vendor": "해룡", "parts": 3, "amount": 692000,
                     "dueDate": "2026-09-01", "note": ""},
                    {"vendorClass": "해룡", "vendor": None, "parts": 1, "amount": 5000,
                     "dueDate": "2026-08-25", "note": ""},
                ],
            },
            {
                "seq": 2,
                "purchaseReason": "두 번째 발주단위",
                "dueDate": "2026-09-10",
                "modules": [],
                "vendorGroups": [
                    {"vendorClass": "판금품", "vendor": "오텍", "parts": 2, "amount": 3000,
                     "dueDate": "2026-09-10", "note": ""},
                ],
            },
        ],
    }
    base.update(over)
    return base


async def _record(owner, **over) -> uuid.UUID | None:
    return await svc.record_plan(
        str(owner) if owner is not None else None,
        run_id=over.get("run_id", "run-1"),
        agent_id="purchase-order",
        plan=over.get("plan", _plan()),
        project=over.get("project", {"code": "2297", "name": "CX85-137", "wbs": "PO-X"}),
        bom_summary=over.get("bom_summary", {"modules": 1, "parts": 3}),
    )


async def test_pure_helpers_derive_counts():
    assert svc.plan_unit_count(_plan()) == 2
    assert svc.plan_total_amount(_plan()) == 700000.0
    assert svc.plan_unit_count({}) == 0 and svc.plan_total_amount({"units": None}) == 0.0


async def test_record_plan_writes_row_with_derived_fields(sm, make_user):
    uid = await make_user("po-user", "user")
    pid = await _record(uid)
    assert pid is not None
    async with sm() as s:
        row = (await s.execute(select(PurchaseOrderPlan).where(PurchaseOrderPlan.id == pid))).scalar_one()
    assert row.user_id == uid and row.run_id == "run-1" and row.agent_id == "purchase-order"
    assert row.project_code == "2297" and row.project_name == "CX85-137"
    assert row.wbs == "PO-2026-07-4136"  # plan 값 우선(상태 project.wbs 'PO-X' 아님).
    assert row.unit_count == 2 and row.total_amount == 700000.0
    assert row.plan == _plan() and row.bom_summary == {"modules": 1, "parts": 3}


async def test_record_plan_falls_back_to_state_project(sm, make_user):
    uid = await make_user("po-user2", "user")
    plan = _plan(project={}, wbs=None)
    pid = await _record(uid, plan=plan)
    async with sm() as s:
        row = (await s.execute(select(PurchaseOrderPlan).where(PurchaseOrderPlan.id == pid))).scalar_one()
    assert row.project_code == "2297" and row.project_name == "CX85-137" and row.wbs == "PO-X"


async def test_record_plan_without_owner_is_noop(sm):
    assert await _record(None) is None
    assert await _record("not-a-uuid") is None
    async with sm() as s:
        assert (await s.execute(select(PurchaseOrderPlan))).scalars().all() == []


async def test_list_is_owner_scoped_and_admin_sees_all(client, make_user, auth_as):
    a = await make_user("po-a", "user")
    b = await make_user("po-b", "user")
    admin = await make_user("po-admin", "admin")
    await _record(a, run_id="run-a")
    await _record(b, run_id="run-b")

    auth_as(a)
    r = await client.get("/purchase-order/plans")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and [i["runId"] for i in body["items"]] == ["run-a"]
    item = body["items"][0]
    assert set(item) == {
        "id", "runId", "agentId", "project", "wbs", "unitCount", "totalAmount",
        "userId", "userDisplayName", "createdAt",
    }
    assert item["userId"] == str(a) and item["userDisplayName"] == "po-a"
    assert item["project"] == {"code": "2297", "name": "CX85-137"}
    assert item["unitCount"] == 2 and item["totalAmount"] == 700000.0

    auth_as(admin)
    r = await client.get("/purchase-order/plans")
    assert r.status_code == 200
    assert r.json()["total"] == 2
    assert {i["runId"] for i in r.json()["items"]} == {"run-a", "run-b"}


async def test_detail_includes_plan_and_hides_others(client, make_user, auth_as):
    a = await make_user("po-a", "user")
    b = await make_user("po-b", "user")
    admin = await make_user("po-admin", "admin")
    pid = await _record(a)

    auth_as(a)
    r = await client.get(f"/purchase-order/plans/{pid}")
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == _plan() and r.json()["bomSummary"] == {"modules": 1, "parts": 3}

    auth_as(b)
    assert (await client.get(f"/purchase-order/plans/{pid}")).status_code == 404
    assert (await client.get("/purchase-order/plans/not-a-uuid")).status_code == 404
    assert (await client.get(f"/purchase-order/plans/{uuid.uuid4()}")).status_code == 404

    auth_as(admin)
    assert (await client.get(f"/purchase-order/plans/{pid}")).status_code == 200
