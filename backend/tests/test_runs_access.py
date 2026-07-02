"""P1-A 실행(runs) 권한·조직접근 게이트 테스트.

runs.collect 신규 세션 경로:
- allowlist: workflow_id 로 Agent 역조회 실패 시 404(demo-echo 등 미매핑 자동 차단).
- 조직접근: access_configured=True 에이전트는 user 롤에 한해 소속 조직구분 검사
  (org_unit 미지정→403, 접근 없음→403, 허용 조직구분→통과, admin+→우회).
전 엔드포인트 AGENTS_RUN 강제(권한 미보유 롤은 403). 재연결 경로는 조직접근 재검사 안 함.
"""

from __future__ import annotations

import pytest

from app.live.registry import register_workflow
from app.main import app as fastapi_app


class _FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        ev = state["events"]
        await ev.put({"step": "s", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.fixture(autouse=True)
def _wire_workflow():
    register_workflow("gated-wf", lambda: _FakeGraph())
    fastapi_app.state.browser_factory = _fake_browser_factory
    yield


@pytest.mark.asyncio
async def test_unmapped_workflow_blocked_404(client, make_user, auth_as):
    """등록된 워크플로우라도 매핑된 Agent 가 없으면 404(allowlist)."""
    uid = await make_user("u-nomap", "user")
    auth_as(uid)
    # gated-wf 는 레지스트리엔 있지만 Agent 행이 없다 → 실행 불가.
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_open_agent_runs_without_org(client, make_user, make_agent, auth_as):
    """access_configured=False(최초·전체 허용)면 org_unit 없이도 실행 가능."""
    uid = await make_user("u-open", "user")
    auth_as(uid)
    await make_agent("a-open", workflow_id="gated-wf", access_configured=False)
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_configured_agent_requires_org_unit_403(client, make_user, make_agent, auth_as):
    """명시 설정 에이전트 + org_unit 미지정 user → 403."""
    uid = await make_user("u-noorg", "user")
    auth_as(uid)
    await make_agent("a-cfg", workflow_id="gated-wf", access_configured=True, allowed_org_units=("sales",))
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_configured_agent_org_not_allowed_403(
    client, make_user, make_agent, set_user_org, auth_as
):
    """소속 조직구분이 허용 목록에 없으면 403."""
    uid = await make_user("u-wrongorg", "user")
    await set_user_org(uid, "mgmt")  # 허용은 sales 뿐
    auth_as(uid)
    await make_agent("a-cfg2", workflow_id="gated-wf", access_configured=True, allowed_org_units=("sales",))
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_configured_agent_allowed_org_passes(
    client, make_user, make_agent, set_user_org, auth_as
):
    """소속 조직구분이 허용 목록에 있으면 실행(200)."""
    uid = await make_user("u-okorg", "user")
    await set_user_org(uid, "sales")
    auth_as(uid)
    await make_agent("a-cfg3", workflow_id="gated-wf", access_configured=True, allowed_org_units=("sales",))
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_bypasses_org_gate(client, make_user, make_agent, auth_as):
    """admin 은 org_unit 미지정이라도 조직 게이트를 우회한다."""
    uid = await make_user("u-admin", "admin")
    auth_as(uid)
    await make_agent("a-cfg4", workflow_id="gated-wf", access_configured=True, allowed_org_units=("sales",))
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_agents_run_permission_required_403(client, make_user, make_agent, auth_as, sm):
    """AGENTS_RUN 권한이 없는 롤(권한 박탈)은 전 엔드포인트에서 403."""
    from sqlalchemy import select

    from app.models import RolePermission, User

    uid = await make_user("u-strip", "user")
    # user 롤에서 agents:run 권한 행을 제거해 권한 미보유 상태를 만든다.
    async with sm() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one()
        role_id = u.role_id
        rps = (
            await s.execute(select(RolePermission).where(RolePermission.role_id == role_id))
        ).scalars().all()
        for rp in rps:
            if rp.permission.code == "agents:run":
                await s.delete(rp)
        await s.commit()
    auth_as(uid)
    await make_agent("a-perm", workflow_id="gated-wf", access_configured=False)
    r = await client.post("/runs/collect", json={"agentId": "gated-wf"})
    assert r.status_code == 403
