"""/runs 라우터 테스트 — SSE 수집 라우트 형태 + HITL 응답 + AgentRun 영속.

브라우저는 fake browser_factory(app.state override)로 대체하고, 워크플로우는 events 큐만
쓰는 fake 그래프를 등록해 실제 헤드리스 브라우저 없이 SSE happy path 까지 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.live import store
from app.live.hitl import (
    _hitl_queues,
    close_hitl_channel,
    open_hitl_channel,
    set_hitl_owner,
)
from app.live.registry import register_workflow
from app.main import app as fastapi_app


class _FakeGraph:
    """events 큐에 step/log 를 넣고 result 를 반환하는 fake 그래프(브라우저 미사용)."""

    async def ainvoke(self, state: dict) -> dict:
        ev = state["events"]
        await ev.put({"step": "테스트", "status": "running"})
        await ev.put({"log": "hi", "level": "info"})
        await ev.put({"step": "테스트", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None  # page None → screencast 스킵, 페이지 조작 없음

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.mark.asyncio
async def test_collect_requires_auth(client):
    r = await client.post("/runs/collect", json={"agentId": "demo-echo"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_collect_unknown_workflow_404(client, make_user, auth_as):
    uid = await make_user("alice", "user")
    auth_as(uid)
    r = await client.post("/runs/collect", json={"agentId": "does-not-exist"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_collect_resume_gone_returns_410(client, make_user, auth_as):
    uid = await make_user("bob", "user")
    auth_as(uid)
    # runId 있고 cursor>0 인데 세션이 없다 → 흐름 종료(410).
    r = await client.post(
        "/runs/collect", json={"runId": "run-missing", "agentId": "demo-echo", "cursor": 3}
    )
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_collect_sse_happy_path(client, make_user, make_agent, auth_as):
    uid = await make_user("carol", "user")
    auth_as(uid)
    # 실행 allowlist: workflow_id=test-echo 로 매핑된 Agent 필요(access_configured=False → 조직게이트 없음).
    await make_agent("echo-agent", workflow_id="test-echo")
    register_workflow("test-echo", lambda: _FakeGraph())
    fastapi_app.state.browser_factory = _fake_browser_factory
    # runId 없음 → 익명 세션(DB 영속 없이 SSE 형태만 검증).
    r = await client.post("/runs/collect", json={"agentId": "test-echo"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert '"step": "\\ud14c\\uc2a4\\ud2b8"' in body or '"step": "테스트"' in body
    assert '"result": "ok"' in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_hitl_unknown_decision_returns_not_resolved(client, make_user, auth_as):
    uid = await make_user("dave", "user")
    auth_as(uid)
    r = await client.post("/runs/hitl", json={"decisionId": "nope"})
    assert r.status_code == 200
    assert r.json() == {"ok": False}


@pytest.mark.asyncio
async def test_hitl_owner_mismatch_forbidden(client, make_user, auth_as):
    uid = await make_user("erin", "user")
    auth_as(uid)
    set_hitl_owner("dec-other", "someone-else")
    _hitl_queues["dec-other"] = asyncio.Queue()
    try:
        r = await client.post("/runs/hitl", json={"decisionId": "dec-other"})
        assert r.status_code == 403
    finally:
        _hitl_queues.pop("dec-other", None)


@pytest.mark.asyncio
async def test_hitl_resolves_owned_decision(client, make_user, auth_as):
    uid = await make_user("frank", "user")
    auth_as(uid)
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues["dec-frank"] = q
    set_hitl_owner("dec-frank", str(uid))
    try:
        r = await client.post("/runs/hitl", json={"decisionId": "dec-frank", "value": "yes"})
        assert r.json() == {"ok": True}
        payload = q.get_nowait()
        assert payload["value"] == "yes"
    finally:
        _hitl_queues.pop("dec-frank", None)


@pytest.mark.asyncio
async def test_hitl_grid_rows_preserve_edited_flags(client, make_user, auth_as):
    """개입 학습 회귀(2026-07-05): 프론트가 보낸 budgetEdited/noteEdited 가 GridRowIn 을 통과해
    큐 payload 에 남아야 한다. 모델에 필드가 없으면 model_dump 에서 버려져 '바꾼 필드만 학습'이
    전량 0건이 됐다."""
    uid = await make_user("edit-flags", "user")
    auth_as(uid)
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues["dec-edit"] = q
    set_hitl_owner("dec-edit", str(uid))
    try:
        r = await client.post(
            "/runs/hitl",
            json={
                "decisionId": "dec-edit",
                "rows": [
                    {
                        "no": 1,
                        "budgetUnit": {"code": "B", "name": "n"},
                        "note": "x",
                        "budgetEdited": True,
                        "noteEdited": True,
                    }
                ],
            },
        )
        assert r.json() == {"ok": True}
        row = q.get_nowait()["rows"][0]
        assert row["budgetEdited"] is True
        assert row["noteEdited"] is True
        assert row["projectEdited"] is False  # 미전송 기본값
    finally:
        _hitl_queues.pop("dec-edit", None)


@pytest.mark.asyncio
async def test_hitl_owner_bound_at_channel_open_forbidden(client, make_user, auth_as):
    """채널 오픈 시점에 바인딩된 소유자(레이스 창 제거)를 /runs/hitl 이 존중한다 — 타인은 403."""
    uid = await make_user("heidi", "user")
    auth_as(uid)
    open_hitl_channel("dec-open", owner="someone-else")
    try:
        r = await client.post("/runs/hitl", json={"decisionId": "dec-open"})
        assert r.status_code == 403
    finally:
        close_hitl_channel("dec-open")


@pytest.mark.asyncio
async def test_hitl_run_id_mismatch_forbidden(client, make_user, auth_as):
    """채널이 특정 run_id 에 묶여 있으면, 요청 runId 가 다를 때 403(불일치 흐름으로의 주입 차단)."""
    uid = await make_user("ivan", "user")
    auth_as(uid)
    open_hitl_channel("dec-run", owner=str(uid), run_id="run-A")
    try:
        mismatch = await client.post(
            "/runs/hitl", json={"decisionId": "dec-run", "runId": "run-B", "value": "yes"}
        )
        assert mismatch.status_code == 403
        # 일치하는 runId 는 정상 통과(resolve True).
        match = await client.post(
            "/runs/hitl", json={"decisionId": "dec-run", "runId": "run-A", "value": "yes"}
        )
        assert match.json() == {"ok": True}
    finally:
        close_hitl_channel("dec-run")


@pytest.mark.asyncio
async def test_hitl_grid_rows_pass_through_to_channel(client, make_user, auth_as):
    """그리드 일괄 제출(rows)이 plain dict 목록으로 채널에 전달된다(노드가 서버검증)."""
    uid = await make_user("judy", "user")
    auth_as(uid)
    q = open_hitl_channel("dec-grid", owner=str(uid))
    try:
        r = await client.post(
            "/runs/hitl",
            json={
                "decisionId": "dec-grid",
                "rows": [
                    {"no": 1, "budgetUnit": {"code": "2000", "name": "경영본부"}, "note": "회식"},
                    {"no": 2, "skip": True},
                ],
            },
        )
        assert r.json() == {"ok": True}
        payload = q.get_nowait()
        assert payload["rows"][0]["budgetUnit"] == {
                "code": "2000", "name": "경영본부", "bizplanNm": None, "bgacctNm": None, "wbsNo": None,
            }  # 조합/WBS 필드는 옵셔널(미전송 시 None 통과)
        assert payload["rows"][1] == {
            "no": 2, "budgetUnit": None, "project": None, "note": "", "skip": True,
            "budgetEdited": False, "projectEdited": False, "noteEdited": False,
        }
    finally:
        close_hitl_channel("dec-grid")


@pytest.mark.asyncio
async def test_hitl_grid_rows_over_limit_422(client, make_user, auth_as):
    uid = await make_user("mallory", "user")
    auth_as(uid)
    rows = [{"no": i + 1, "skip": True} for i in range(501)]  # max_length=500 초과
    r = await client.post("/runs/hitl", json={"decisionId": "d", "rows": rows})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_hitl_grid_row_bad_shape_422(client, make_user, auth_as):
    uid = await make_user("oscar", "user")
    auth_as(uid)
    # no<1 (ge=1 위반) + budgetUnit.code 초과 → 검증 실패.
    bad_no = await client.post("/runs/hitl", json={"decisionId": "d", "rows": [{"no": 0}]})
    assert bad_no.status_code == 422
    bad_code = await client.post(
        "/runs/hitl",
        json={"decisionId": "d", "rows": [{"no": 1, "budgetUnit": {"code": "x" * 65, "name": "n"}}]},
    )
    assert bad_code.status_code == 422


@pytest.mark.asyncio
async def test_agent_run_persistence_roundtrip(make_user):
    uid = await make_user("grace", "user")
    await store.create_run(run_id="run-persist", agent_id="demo-echo", user_id=uid)
    run = await store.get_run("run-persist")
    assert run is not None
    assert run.status == "running"
    assert str(run.user_id) == str(uid)

    logs = [{"ts": 1, "level": "ok", "message": "done"}]
    await store.set_terminal("run-persist", "succeeded", "결과", logs)
    run2 = await store.get_run("run-persist")
    assert run2.status == "succeeded"
    assert run2.result == "결과"
    assert run2.finished_at is not None
    assert run2.logs == logs


# ── 즉시 종료(cancel) ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cancel_marks_running_run_cancelled(client, make_user, auth_as):
    uid = await make_user("cara", "user")
    auth_as(uid)
    await store.create_run(run_id="run-cxl", agent_id="demo-echo", user_id=uid)
    r = await client.post("/runs/cancel", json={"runId": "run-cxl"})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    run = await store.get_run("run-cxl")
    assert run.status == "cancelled"
    assert run.finished_at is not None
    # 멱등 — 이미 cancelled 여도 200(추가 변경 없음).
    r2 = await client.post("/runs/cancel", json={"runId": "run-cxl"})
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_cancel_other_users_run_not_found(client, make_user, auth_as):
    owner = await make_user("owner1", "user")
    other = await make_user("other1", "user")
    await store.create_run(run_id="run-owned", agent_id="demo-echo", user_id=owner)
    auth_as(other)
    r = await client.post("/runs/cancel", json={"runId": "run-owned"})
    assert r.status_code == 404
    run = await store.get_run("run-owned")
    assert run.status == "running"  # 남의 취소로 바뀌지 않음


@pytest.mark.asyncio
async def test_cancel_missing_run_is_idempotent_200(client, make_user, auth_as):
    uid = await make_user("cane", "user")
    auth_as(uid)
    r = await client.post("/runs/cancel", json={"runId": "run-nonexistent"})
    assert r.status_code == 200


# ── 실행 이력(run history) ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_runs_owner_scoped_and_filtered(client, make_user, auth_as):
    uid = await make_user("hank", "user")
    other = await make_user("iris", "user")
    await store.create_run(run_id="run-h1", agent_id="demo-echo", user_id=uid)
    await store.set_terminal(
        "run-h1", "succeeded", "요약1", [{"ts": 1, "level": "ok", "message": "a"}]
    )
    await store.create_run(run_id="run-h2", agent_id="expense-card-chat", user_id=uid)
    await store.create_run(run_id="run-other", agent_id="demo-echo", user_id=other)

    auth_as(uid)
    r = await client.get("/runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    ids = {x["id"] for x in runs}
    assert {"run-h1", "run-h2"} <= ids
    assert "run-other" not in ids  # 소유자 스코프
    # camelCase 요약 필드.
    first = runs[0]
    assert {"id", "agentId", "status", "startedAt", "finishedAt", "resultSummary"} <= set(first)
    # 최신순(startedAt 내림차순 — ISO 문자열 비교).
    starts = [x["startedAt"] for x in runs]
    assert starts == sorted(starts, reverse=True)
    # agentId 필터.
    r2 = await client.get("/runs", params={"agentId": "expense-card-chat"})
    assert [x["id"] for x in r2.json()["runs"]] == ["run-h2"]


@pytest.mark.asyncio
async def test_list_runs_total_reflects_scope_and_filter(client, make_user, auth_as):
    """{runs, total} envelope — total 은 페이지가 아닌 스코프 전체 건수(필터 반영)."""
    uid = await make_user("tara", "user")
    other = await make_user("uma", "user")
    for i in range(3):
        await store.create_run(run_id=f"run-t{i}", agent_id="demo-echo", user_id=uid)
    await store.create_run(run_id="run-t-exp", agent_id="expense-card-chat", user_id=uid)
    await store.create_run(run_id="run-t-other", agent_id="demo-echo", user_id=other)

    auth_as(uid)
    # limit<보유 건수 라도 total 은 소유 스코프 전체(=4), 타인 것 미포함.
    body = (await client.get("/runs", params={"limit": 2})).json()
    assert body["total"] == 4
    assert len(body["runs"]) == 2
    # agentId 필터 시 total 도 필터 반영.
    filtered = (await client.get("/runs", params={"agentId": "demo-echo"})).json()
    assert filtered["total"] == 3


@pytest.mark.asyncio
async def test_list_runs_admin_sees_all_users_own_scoped_otherwise(client, make_user, auth_as):
    u1 = await make_user("nadia", "user")
    u2 = await make_user("omar", "user")
    admin = await make_user("adm", "admin")  # admin 롤은 logs:read 보유
    await store.create_run(run_id="run-u1", agent_id="demo-echo", user_id=u1)
    await store.create_run(run_id="run-u2", agent_id="demo-echo", user_id=u2)

    # 일반 사용자 u1 → 본인 것만.
    auth_as(u1)
    assert {x["id"] for x in (await client.get("/runs")).json()["runs"]} == {"run-u1"}

    # admin(logs:read) → 전체 유저의 run.
    auth_as(admin)
    runs = (await client.get("/runs")).json()["runs"]
    ids = {x["id"] for x in runs}
    assert {"run-u1", "run-u2"} <= ids
    # userId + userDisplayName 로 실행 주체 식별(로깅 뷰). make_user 는 display_name=userid.
    by_id = {x["id"]: x for x in runs}
    assert by_id["run-u1"]["userId"] == str(u1) and by_id["run-u2"]["userId"] == str(u2)
    assert by_id["run-u1"]["userDisplayName"] == "nadia"
    assert by_id["run-u2"]["userDisplayName"] == "omar"
    # admin 은 남의 상세도 열람 가능(로깅 뷰 일관성).
    assert (await client.get("/runs/run-u1")).status_code == 200


@pytest.mark.asyncio
async def test_failed_step_in_summary_and_steps_in_detail(client, make_user, auth_as):
    uid = await make_user("pat", "user")
    # 구조 필드 없이 message 만 있는 옛 로그도 파싱되어야 한다(폴백 파서).
    logs = [
        {"ts": 1, "level": "ok", "message": "✓ login (done)"},
        {"ts": 2, "level": "info", "message": "▶ chat_form (running)"},
        {"ts": 3, "level": "error", "message": "✗ chat_form (failed)"},
    ]
    await store.create_run(run_id="run-f", agent_id="expense-card-chat", user_id=uid)
    await store.set_terminal("run-f", "failed", "대화형 폼 입력 대기 시간 초과", logs)

    auth_as(uid)
    summary = next(x for x in (await client.get("/runs")).json()["runs"] if x["id"] == "run-f")
    assert summary["status"] == "failed"
    assert summary["failedStep"] == "chat_form"  # 마지막 실패 단계

    d = (await client.get("/runs/run-f")).json()
    steps = {(s["step"], s["status"]) for s in d["steps"]}
    assert ("login", "done") in steps and ("chat_form", "failed") in steps


@pytest.mark.asyncio
async def test_succeeded_run_has_null_failed_step(client, make_user, auth_as):
    uid = await make_user("rob", "user")
    await store.create_run(run_id="run-ok", agent_id="demo-echo", user_id=uid)
    await store.set_terminal("run-ok", "succeeded", "ok", [{"ts": 1, "level": "ok", "message": "✓ echo (done)"}])
    auth_as(uid)
    summary = next(x for x in (await client.get("/runs")).json()["runs"] if x["id"] == "run-ok")
    assert summary["failedStep"] is None  # 성공 실행은 failedStep 없음


@pytest.mark.asyncio
async def test_run_detail_exposes_inputs_selections_and_messages(client, make_user, auth_as):
    uid = await make_user("quinn", "user")
    result = {
        "summary": "대화형 폼 완료",
        "selections": [{"tool": "fill_text", "field": "적요", "value": "메모"}],
        "messages": ["적요 메모로 채워줘"],
    }
    await store.create_run(run_id="run-in", agent_id="expense-card-chat", user_id=uid)
    await store.set_terminal("run-in", "succeeded", result, [])
    auth_as(uid)
    d = (await client.get("/runs/run-in")).json()
    assert d["inputs"]["selections"][0]["field"] == "적요"
    assert d["inputs"]["messages"] == ["적요 메모로 채워줘"]


@pytest.mark.asyncio
async def test_get_run_detail_owner_scoped_with_structured_result(client, make_user, auth_as):
    uid = await make_user("jack", "user")
    other = await make_user("kim", "user")
    await store.create_run(run_id="run-d1", agent_id="expense-card-chat", user_id=uid)
    logs = [{"ts": 1, "level": "ok", "message": "hi"}]
    # 대화형 완료 결과(구조 — summary + selections)가 run.result 로 회수된다.
    result = {
        "summary": "대화형 폼 완료",
        "selections": [{"tool": "fill_text", "field": "적요", "value": "메모"}],
    }
    await store.set_terminal("run-d1", "succeeded", result, logs)

    auth_as(uid)
    r = await client.get("/runs/run-d1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "run-d1"
    assert body["result"]["selections"][0]["field"] == "적요"
    assert body["logs"] == logs
    assert body["resultSummary"] == "대화형 폼 완료"  # dict → summary 우선

    auth_as(other)
    assert (await client.get("/runs/run-d1")).status_code == 404  # 다른 사용자는 404


# ── 템플릿 CRUD ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_templates_crud_owner_scoped(client, make_user, auth_as):
    uid = await make_user("lee", "user")
    other = await make_user("moon", "user")
    auth_as(uid)
    sels = [
        {"tool": "set_expense", "field": "예산단위", "value": "야근식대", "query": "제조"},
        {"tool": "fill_text", "field": "적요", "value": "직원 야근 식대(법인카드)"},
    ]
    r = await client.post(
        "/runs/templates",
        json={"agentId": "expense-card-chat", "name": "야근", "selections": sels},
    )
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["name"] == "야근"
    assert r.json()["selections"] == sels
    assert "createdAt" in r.json()

    # 목록(소유자 + agentId 필터) — '/runs/templates' 가 '/runs/{run_id}' 로 잡히지 않음.
    r2 = await client.get("/runs/templates", params={"agentId": "expense-card-chat"})
    assert [t["id"] for t in r2.json()["templates"]] == [tid]

    # 다른 사용자 목록엔 안 보이고, 삭제도 404(소유자 스코프).
    auth_as(other)
    assert (await client.get("/runs/templates")).json()["templates"] == []
    assert (await client.delete(f"/runs/templates/{tid}")).status_code == 404

    # 소유자 삭제 → 목록에서 사라진다.
    auth_as(uid)
    assert (await client.delete(f"/runs/templates/{tid}")).status_code == 200
    assert (await client.get("/runs/templates")).json()["templates"] == []
