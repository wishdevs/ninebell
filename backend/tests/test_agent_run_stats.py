"""에이전트 실행 통계 — serialize_agent 가 픽스처 목업이 아니라 agent_runs 실 이력을 집계한다.

이전엔 card-chat 픽스처의 하드코딩(run_count=23 등)이 표시됐다. 이제 실 실행 이력에서
실행수·성공률·평균시간·최근실행을 계산한다(실행 없으면 0/None).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import AgentRun

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)


async def _add_run(sm, *, rid, agent_id, user_id, status, started, dur_s) -> None:
    async with sm() as s:
        s.add(
            AgentRun(
                id=rid,
                agent_id=agent_id,
                user_id=user_id,
                status=status,
                started_at=started,
                finished_at=(started + timedelta(seconds=dur_s)) if dur_s is not None else None,
                logs=[],
            )
        )
        await s.commit()


async def test_agent_stats_from_real_runs(client, make_user, auth_as, sm):
    uid = await make_user("stats-user", "super_admin")
    # 성공 2(60s·120s) + 실패 1(30s) + 진행중 1(미완).
    await _add_run(sm, rid="r1", agent_id="card-chat", user_id=uid, status="succeeded", started=_T0, dur_s=60)
    await _add_run(sm, rid="r2", agent_id="card-chat", user_id=uid, status="succeeded", started=_T0 + timedelta(hours=1), dur_s=120)
    await _add_run(sm, rid="r3", agent_id="card-chat", user_id=uid, status="failed", started=_T0 + timedelta(hours=2), dur_s=30)
    await _add_run(sm, rid="r4", agent_id="card-chat", user_id=uid, status="running", started=_T0 + timedelta(hours=3), dur_s=None)

    auth_as(uid)
    body = (await client.get("/agents/card-chat")).json()
    assert body["runCount"] == 4  # 전체(진행중 포함)
    assert body["successRate"] == 66.7  # 2/(2+1)
    assert body["avgSeconds"] == 70  # (60+120+30)/3 완료 런 평균
    assert body["lastRunAt"] is not None  # r4 시작(최신)


async def test_agent_stats_zero_when_no_runs(client, make_user, auth_as):
    uid = await make_user("stats-empty", "super_admin")
    auth_as(uid)
    body = (await client.get("/agents/trip-domestic")).json()
    assert body["runCount"] == 0
    assert body["avgSeconds"] == 0
    assert body["successRate"] == 0.0
    assert body["lastRunAt"] is None


async def test_list_agents_stats_scoped_per_agent(client, make_user, auth_as, sm):
    # 목록에서도 에이전트별로 자기 실행만 집계된다(다른 에이전트 실행이 섞이지 않음).
    uid = await make_user("stats-list", "super_admin")
    await _add_run(sm, rid="l1", agent_id="card-chat", user_id=uid, status="succeeded", started=_T0, dur_s=100)
    auth_as(uid)
    rows = (await client.get("/agents")).json()
    by_id = {a["id"]: a for a in rows}
    assert by_id["card-chat"]["runCount"] == 1
    assert by_id["trip-domestic"]["runCount"] == 0


# ── 숨김 에이전트(hidden=True) — 목록 제외 + 상세 404 ─────────────────────────
async def test_hidden_agents_excluded_from_list(client, make_user, auth_as):
    uid = await make_user("hide-list", "super_admin")
    auth_as(uid)
    rows = (await client.get("/agents")).json()
    ids = {a["id"] for a in rows}
    # 카드·국내출장만 노출, 해외출장·경조금·학자금은 숨김.
    assert "card-chat" in ids and "trip-domestic" in ids
    assert "trip-overseas" not in ids
    assert "family-event" not in ids and "scholarship" not in ids


async def test_hidden_agent_detail_returns_404(client, make_user, auth_as):
    uid = await make_user("hide-detail", "super_admin")
    auth_as(uid)
    assert (await client.get("/agents/trip-overseas")).status_code == 404
