"""422(경계 검증 실패) 표면화 — 서버 로그에 필드·사유가 남고 응답에 읽을 수 있는 error 가 병기된다.

2026-08-28 계획서 제출 422 사고: 요청 로그는 body 를 잘라 어느 필드가 왜 튕겼는지 알 수 없었다.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.asyncio


async def test_hitl_422_logs_field_and_returns_readable_error(client, make_user, auth_as, caplog):
    uid = await make_user("v422", "user")
    auth_as(uid)
    plan = {
        "project": {"code": "P1", "name": "프로젝트"},
        "wbs": "W",
        "units": [
            {
                "seq": 1,
                "purchaseReason": "사유",
                "dueDate": "2026-09-01",
                "modules": [{"itemCode": "SET-1"}],
                "vendorGroups": [{"vendorClass": "", "vendor": "x", "parts": 1, "amount": 0}],
            }
        ],
    }
    with caplog.at_level(logging.WARNING, logger="app.main"):
        resp = await client.post(
            "/runs/hitl", json={"runId": "run-x", "decisionId": "d1", "plan": plan}
        )
    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body["detail"], list) and body["detail"]
    assert body["error"].startswith("요청 형식 오류 — ")
    assert "plan.units.0.vendorGroups.0.vendorClass" in body["error"]
    logged = [r.getMessage() for r in caplog.records if "422 POST /runs/hitl" in r.getMessage()]
    assert logged and "vendorGroups.0.vendorClass" in logged[0]
