"""단계별 expectedMs 테스트 — 최근 성공 런 logs 실측 평균 계산 + 상세 API 서빙.

expected_step_ms 의 평균/합산/제외 규칙과, GET /agents/{id} 응답에만 expectedMs 가
실리는지(목록엔 없음)를 conftest 픽스처(client/make_user/make_agent/auth_as)로 검증한다.
"""

from __future__ import annotations

import itertools

import pytest

from app.models.agent_run import AgentRun
from app.services import step_timings
from app.services.step_timings import expected_step_ms

_seq = itertools.count()


def _frames(step: str, start: int, end: int, status: str = "done") -> list[dict]:
    """단계 running→종료 프레임 한 쌍(smoke_cycle 로그 포맷)."""
    return [
        {"ts": start, "level": "info", "message": f"{step}…", "step": step, "status": "running"},
        {"ts": end, "level": "ok", "message": f"{step} 끝", "step": step, "status": status},
    ]


@pytest.fixture(autouse=True)
def _clear_cache():
    """모듈 전역 TTL 캐시가 테스트 간 새지 않도록 비운다."""
    step_timings._cache.clear()
    yield
    step_timings._cache.clear()


@pytest.fixture
def make_run(sm):
    """AgentRun 행 생성 헬퍼 — workflow_id/status/logs 지정."""

    async def _make(workflow_id: str, user_id, *, status: str = "succeeded", logs=None):
        async with sm() as s:
            s.add(
                AgentRun(
                    id=f"run-t{next(_seq)}",
                    agent_id=workflow_id,
                    user_id=user_id,
                    status=status,
                    logs=logs,
                )
            )
            await s.commit()

    return _make


@pytest.mark.asyncio
async def test_average_across_runs(sm, make_user, make_run):
    """성공 런 2개의 step 별 ms 평균(int)을 낸다."""
    uid = await make_user("st-avg", "user")
    await make_run("st-wf1", uid, logs=_frames("login", 0, 1000) + _frames("save", 1000, 3000))
    await make_run("st-wf1", uid, logs=_frames("login", 0, 3000) + _frames("save", 3000, 7000))
    async with sm() as s:
        result = await expected_step_ms(s, "st-wf1")
    assert result == {"login": 2000, "save": 3000}


@pytest.mark.asyncio
async def test_repeated_step_summed_within_run(sm, make_user, make_run):
    """재시도로 같은 step 이 한 런에 여러 번 나오면 런 내 합산(failed 구간 포함)."""
    uid = await make_user("st-retry", "user")
    logs = _frames("save", 0, 1000, status="failed") + _frames("save", 2000, 3000)
    await make_run("st-wf2", uid, logs=logs)
    async with sm() as s:
        result = await expected_step_ms(s, "st-wf2")
    assert result == {"save": 2000}  # 1000(실패 시도) + 1000(성공 시도)


@pytest.mark.asyncio
async def test_failed_runs_excluded(sm, make_user, make_run):
    """status != succeeded 런은 표본에서 제외한다."""
    uid = await make_user("st-fail", "user")
    await make_run("st-wf3", uid, logs=_frames("login", 0, 1000))
    await make_run("st-wf3", uid, status="failed", logs=_frames("login", 0, 99000))
    async with sm() as s:
        result = await expected_step_ms(s, "st-wf3")
    assert result == {"login": 1000}


@pytest.mark.asyncio
async def test_empty_or_unparsable_logs_skipped(sm, make_user, make_run):
    """logs 가 None/빈 리스트/단계 프레임 없음인 런은 건너뛰고, 전부 그러면 빈 dict."""
    uid = await make_user("st-empty", "user")
    await make_run("st-wf4", uid, logs=None)
    await make_run("st-wf4", uid, logs=[])
    await make_run("st-wf4", uid, logs=[{"ts": 1, "level": "info", "message": "no step"}])
    async with sm() as s:
        assert await expected_step_ms(s, "st-wf4") == {}

    # 유효 런이 섞이면 그 런만 표본이 된다.
    await make_run("st-wf4", uid, logs=_frames("login", 0, 500))
    step_timings._cache.clear()  # 위 호출이 빈 결과를 캐시했으므로 무효화.
    async with sm() as s:
        assert await expected_step_ms(s, "st-wf4") == {"login": 500}


@pytest.mark.asyncio
async def test_detail_api_serves_expected_ms_but_list_does_not(
    sm, client, make_user, make_agent, make_run, auth_as
):
    """상세 응답 steps[] 에는 expectedMs 가 실리고, 목록 응답에는 없다."""
    from app.models import AgentStep

    uid = await make_user("st-api", "admin")
    auth_as(uid)
    await make_agent("st-agent", workflow_id="st-wf5")
    async with sm() as s:
        s.add(AgentStep(agent_id="st-agent", key="login", label="로그인", status="pending", position=0))
        s.add(AgentStep(agent_id="st-agent", key="etc", label="기타", status="pending", position=1))
        await s.commit()
    await make_run("st-wf5", uid, logs=_frames("login", 0, 1500))

    detail = (await client.get("/agents/st-agent")).json()
    by_key = {st["id"]: st for st in detail["steps"]}
    assert by_key["login"]["expectedMs"] == 1500
    assert "expectedMs" not in by_key["etc"]  # 표본 없는 단계는 필드 자체가 없다.

    listing = (await client.get("/agents")).json()
    agent = next(a for a in listing if a["id"] == "st-agent")
    assert all("expectedMs" not in st for st in agent["steps"])
