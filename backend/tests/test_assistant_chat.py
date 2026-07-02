"""AI 어시스턴트 채팅(SSE) 라우터 테스트.

- 미인증 401(스트림 시작 전).
- happy path: 프로바이더를 가짜로 대체해 delta·action·done 을 SSE 프레임으로 검증.
- 키 누락: build_llm 이 RuntimeError → 종료 에러 프레임(HTTP 200 유지).
- 422: 메시지 수 초과 / 개별 content 길이 초과.
"""

from __future__ import annotations

import app.routers.assistant as assistant
from app.llm.base import ChatChunk


class _FakeProvider:
    name = "fake"

    async def chat(self, messages, *, system=None, temperature=0.7, max_output_tokens=8192, tools=None):
        yield ChatChunk(delta="안녕하세요")
        yield ChatChunk(delta="", tool_call={"name": "suggest_agent", "args": {"agentId": "a1", "intent": "open"}})
        yield ChatChunk(delta="", done=True, finish_reason="STOP")

    async def aclose(self) -> None:
        return None


async def test_chat_unauthenticated_returns_401(client):
    # get_current_user 오버라이드 없이(쿠키 없음) → 스트림 시작 전 401.
    resp = await client.post("/assistant/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
    assert resp.status_code == 401


async def test_chat_happy_path_streams_delta_action_done(client, make_user, auth_as, monkeypatch):
    uid = await make_user("u-chat", "user")
    auth_as(uid)
    monkeypatch.setattr(assistant, "build_llm", lambda request, settings: _FakeProvider())

    resp = await client.post(
        "/assistant/chat",
        json={
            "messages": [{"role": "user", "content": "a1 열어줘"}],
            "context": {"agents": [{"id": "a1", "name": "테스트"}], "runs": []},
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert '"delta"' in body
    assert '안녕하세요' in body
    assert '"action"' in body
    assert 'suggest_agent' in body
    assert "data: [DONE]" in body
    # 에러 프레임은 없어야 한다.
    assert '"error"' not in body


async def test_chat_missing_api_key_yields_error_frame(client, make_user, auth_as, monkeypatch):
    uid = await make_user("u-nokey", "user")
    auth_as(uid)

    def _raise(request, settings):
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않아 AI 어시스턴트를 사용할 수 없습니다.")

    monkeypatch.setattr(assistant, "build_llm", _raise)

    resp = await client.post("/assistant/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
    # 구성 오류는 500 이 아니라 종료 SSE 에러 프레임으로 표면화된다(HTTP 200 유지).
    assert resp.status_code == 200
    body = resp.text
    assert '"error"' in body
    assert "GEMINI_API_KEY" in body
    assert "data: [DONE]" in body


async def test_chat_too_many_messages_returns_422(client, make_user, auth_as):
    uid = await make_user("u-422a", "user")
    auth_as(uid)
    messages = [{"role": "user", "content": "x"} for _ in range(51)]
    resp = await client.post("/assistant/chat", json={"messages": messages})
    assert resp.status_code == 422


async def test_chat_content_too_long_returns_422(client, make_user, auth_as):
    uid = await make_user("u-422b", "user")
    auth_as(uid)
    resp = await client.post(
        "/assistant/chat",
        json={"messages": [{"role": "user", "content": "x" * 8001}]},
    )
    assert resp.status_code == 422


async def test_chat_context_too_large_returns_422(client, make_user, auth_as):
    uid = await make_user("u-422c", "user")
    auth_as(uid)
    resp = await client.post(
        "/assistant/chat",
        json={
            "messages": [{"role": "user", "content": "안녕"}],
            "context": {"agents": [{"id": "a", "name": "x" * 21_000}]},
        },
    )
    assert resp.status_code == 422


async def test_chat_rejected_with_429_when_slot_already_held(client, make_user, auth_as):
    """레이트리밋이 라우터 경로에서 실제로 적용되는지 HTTP 레벨로 확인.

    슬롯을 미리 점유(다른 탭에서 스트림 진행 중을 흉내)한 뒤 요청하면 스트림 시작 전 429.
    """
    from app.main import app as fastapi_app

    uid = await make_user("u-429", "user")
    auth_as(uid)
    limiter = fastapi_app.state.assistant_limiter
    user_key = str(uid)

    held = limiter.try_acquire(user_key)  # 슬롯 점유(진행 중인 다른 요청 흉내)
    assert held is None
    try:
        resp = await client.post(
            "/assistant/chat", json={"messages": [{"role": "user", "content": "안녕"}]}
        )
        assert resp.status_code == 429
    finally:
        limiter.release(user_key)
