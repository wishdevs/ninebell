"""HTTP 요청 로깅 — 인바운드 미들웨어 / 아웃바운드 훅 / LLM 와이어 전문 / 마스킹.

회귀 감시 지점(이 셋이 깨지면 운영 사고):
  1. 요청 본문을 미들웨어가 읽어도 **다운스트림 라우터가 그대로 받는다**(_CachedRequest).
  2. 미들웨어가 **SSE 응답을 버퍼링하지 않는다** — 첫 청크 시점에 이미 로그가 찍혀 있어야 한다.
  3. 로그인 본문의 **평문 비밀번호가 마스킹**된다.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from app.agents.common import prompt_capture
from app.core.http_client import new_async_client
from app.core.logging_setup import configure_logging
from app.core.redact import MASK, body_preview, redact_value, safe_url
from app.core.request_log import HttpRequestLogMiddleware


# ── 마스킹·절단 ────────────────────────────────────────────────────────────────
def test_redact_masks_sensitive_keys_recursively():
    src = {"userid": "admin", "password": "1111", "nested": {"access_token": "t", "keep": 1}}
    out = redact_value(src)

    assert out == {"userid": "admin", "password": MASK, "nested": {"access_token": MASK, "keep": 1}}
    assert src["password"] == "1111"  # 원본 불변(새 객체 반환).


def test_body_preview_masks_password_in_json():
    preview = body_preview(json.dumps({"userid": "admin", "password": "1111"}).encode())

    assert "1111" not in preview
    assert MASK in preview
    assert "admin" in preview


def test_body_preview_hides_non_json_content():
    """폼/멀티파트는 키 기반 마스킹이 불가 — 내용을 남기지 않고 크기만 남긴다."""
    preview = body_preview(b"userid=admin&password=1111")

    assert "1111" not in preview
    assert "non-json" in preview


def test_body_preview_truncates_long_body():
    preview = body_preview(json.dumps({"v": "x" * 9_000}).encode(), max_chars=100)

    assert len(preview) < 200
    assert "자)" in preview  # …(+N자) 꼬리


def test_safe_url_masks_query_secrets():
    """헤더 인증이 기본이지만 base_url 은 env 로 바뀐다 — 쿼리 비밀값은 방어적으로 가린다."""
    out = safe_url("https://api.example/v1/models/x:generate?key=AIzaSECRET&alt=sse")

    assert "AIzaSECRET" not in out
    assert MASK in out
    assert "alt=sse" in out  # 무해한 파라미터는 보존.


def test_safe_url_without_query_is_unchanged():
    url = "http://172.20.50.2:30001/v1/chat/completions"

    assert safe_url(url) == url


def test_body_preview_empty_body():
    assert body_preview(b"") == "-"
    assert body_preview(None) == "-"


# ── 인바운드 미들웨어 ──────────────────────────────────────────────────────────
async def test_inbound_logs_method_path_status_and_masks_password(client, caplog):
    """모든 인바운드 요청이 메서드·경로·상태와 함께 남고, 비밀번호는 가려진다."""
    caplog.set_level(logging.INFO, logger="app.http.in")

    await client.post("/auth/login", json={"userid": "nobody", "password": "1111"})

    records = [r for r in caplog.records if r.name == "app.http.in"]
    assert len(records) == 1
    line = records[0].getMessage()
    assert "POST" in line
    assert "/auth/login" in line
    assert "1111" not in line  # 평문 비밀번호 유출 금지.
    assert MASK in line


async def test_inbound_preserves_request_body_for_router(client):
    """⚠ 회귀 감시: 미들웨어가 본문을 읽어도 라우터가 그대로 받아야 한다.

    본문이 유실되면 pydantic 검증이 '필드 없음'으로 422 를 낸다. 두 방향으로 확인한다.
      · 온전한 본문 → 422 가 **아니다**(본문이 검증을 통과해 핸들러까지 갔다).
      · 필드 누락 본문 → 422 **가 맞다**(검증기가 실제로 본문 내용을 보고 있다 = 위 단정이 유효).
    """
    ok = await client.post("/auth/login", json={"userid": "nobody", "password": "wrong"})
    assert ok.status_code != 422, "요청 본문이 미들웨어에서 소실됐다"

    missing = await client.post("/auth/login", json={"userid": "nobody"})
    assert missing.status_code == 422, "검증기가 본문을 보지 않는다 — 위 단정이 무의미해진다"


async def test_inbound_failure_logged_at_warning_or_error(client, caplog):
    caplog.set_level(logging.INFO, logger="app.http.in")

    await client.get("/runs/does-not-exist")

    records = [r for r in caplog.records if r.name == "app.http.in"]
    assert records, "요청 로그가 없다"
    assert records[-1].levelno >= logging.WARNING  # 4xx/5xx 는 골라볼 수 있어야 한다.


async def test_inbound_does_not_buffer_streaming_response(caplog):
    """⚠ 회귀 감시: SSE 를 버퍼링하면 라이브 화면이 멈춘다.

    각 청크를 만들 때 '요청 로그가 이미 찍혔는지'를 기록해 둔다.
      · 미들웨어가 **전체를 버퍼링**하면 로그는 마지막 청크 뒤에 찍히므로 전부 False 가 된다.
      · 지금처럼 헤더 시점에 흘려보내면 후속 청크는 로그 뒤에 생성돼 True 가 된다.
    첫 청크만 False 인 것은 정상이다 — BaseHTTPMiddleware 의 call_next 는 응답 종류를
    판별하려고 첫 메시지까지 받아본 뒤 반환하기 때문이다(그 다음에 로그가 찍힌다).
    """
    caplog.set_level(logging.INFO, logger="app.http.in")
    logged_when_chunk_made: list[bool] = []

    async def stream(_request):
        async def gen():
            for i in range(3):
                logged_when_chunk_made.append(
                    any(r.name == "app.http.in" for r in caplog.records)
                )
                yield f"data: {i}\n\n".encode()

        return StreamingResponse(gen(), media_type="text/event-stream")

    sse_app = Starlette(routes=[Route("/sse", stream)])
    sse_app.add_middleware(HttpRequestLogMiddleware)

    transport = httpx.ASGITransport(app=sse_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/sse")

    assert res.text == "data: 0\n\ndata: 1\n\ndata: 2\n\n"  # 본문 온전.
    assert len(logged_when_chunk_made) == 3
    assert any(logged_when_chunk_made), (
        "모든 청크가 로그보다 먼저 생성됐다 — 미들웨어가 스트림을 통째로 버퍼링하고 있다"
    )
    assert logged_when_chunk_made[-1] is True


# ── 아웃바운드 훅 ──────────────────────────────────────────────────────────────
async def test_outbound_logs_method_url_status(caplog):
    caplog.set_level(logging.INFO, logger="app.http.out")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with new_async_client(transport=httpx.MockTransport(handler)) as c:
        await c.post("https://llm.example/v1/chat", json={"prompt": "안녕"})

    records = [r for r in caplog.records if r.name == "app.http.out"]
    assert len(records) == 1
    line = records[0].getMessage()
    assert "POST" in line
    assert "https://llm.example/v1/chat" in line
    assert "200" in line
    assert "안녕" in line  # 보낸 내용이 남아야 한다.


async def test_outbound_masks_secrets_and_flags_failure(caplog):
    caplog.set_level(logging.INFO, logger="app.http.out")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with new_async_client(transport=httpx.MockTransport(handler)) as c:
        await c.post("https://llm.example/v1/chat", json={"api_key": "sk-secret"})

    records = [r for r in caplog.records if r.name == "app.http.out"]
    assert records[-1].levelno == logging.ERROR
    assert "sk-secret" not in records[-1].getMessage()


async def test_outbound_preserves_caller_hooks(caplog):
    """호출부가 넘긴 event_hooks 를 팩토리가 덮어쓰지 않는다."""
    called: list[str] = []

    async def mine(_response: httpx.Response) -> None:
        called.append("mine")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    async with new_async_client(
        transport=httpx.MockTransport(handler), event_hooks={"response": [mine]}
    ) as c:
        await c.get("https://x.example/")

    assert called == ["mine"]


# ── LLM 와이어 전문 ────────────────────────────────────────────────────────────
def test_llm_wire_logs_full_request_and_response(caplog):
    """요청·응답 전문이 같은 seq 로 짝지어 남는다(파일 캡처 OFF 여도)."""
    caplog.set_level(logging.INFO, logger="app.llm.wire")

    seq = prompt_capture.capture_request(
        "gemini", "https://llm/x", {"system": "지시문", "contents": [{"text": "카드내역"}]}
    )
    prompt_capture.capture_response("gemini", "https://llm/x", seq, {"candidates": [{"a": 1}]})

    records = [r for r in caplog.records if r.name == "app.llm.wire"]
    assert len(records) == 2
    req, res = records[0].getMessage(), records[1].getMessage()
    assert "request" in req and "지시문" in req and "카드내역" in req
    assert "response" in res and "candidates" in res
    assert f"seq={seq}" in req and f"seq={seq}" in res


def test_llm_wire_masks_credentials_in_url_and_body(caplog):
    """전문 보존이 목적이라도 자격증명은 가린다 — 정상 바디 필드와는 겹치지 않는다."""
    caplog.set_level(logging.INFO, logger="app.llm.wire")

    prompt_capture.capture_request(
        "gemini",
        "https://api.example/v1/models/x:generate?key=AIzaSECRET",
        {"system_instruction": "지시문", "max_tokens": 4096, "api_key": "sk-LEAK"},
    )

    line = [r for r in caplog.records if r.name == "app.llm.wire"][-1].getMessage()
    assert "AIzaSECRET" not in line
    assert "sk-LEAK" not in line
    assert "지시문" in line  # 프롬프트는 보존.
    assert "4096" in line  # max_tokens 는 'token' 과 정확일치가 아니라 살아남는다.


def test_llm_wire_elides_gemini_screenshot(caplog):
    caplog.set_level(logging.INFO, logger="app.llm.wire")
    blob = "A" * 5_000

    prompt_capture.capture_request(
        "gemini",
        "https://llm/x",
        {"contents": [{"parts": [{"text": "판단해줘"}, {"inline_data": {"mime_type": "image/jpeg", "data": blob}}]}]},
    )

    line = [r for r in caplog.records if r.name == "app.llm.wire"][-1].getMessage()
    assert blob not in line
    assert "image base64 생략" in line
    assert "판단해줘" in line  # 프롬프트 텍스트는 보존.


def test_llm_wire_elides_etribe_data_uri(caplog):
    caplog.set_level(logging.INFO, logger="app.llm.wire")
    blob = "data:image/jpeg;base64," + "B" * 5_000

    prompt_capture.capture_request(
        "etribe",
        "https://llm/x",
        {"messages": [{"content": [{"type": "image_url", "image_url": {"url": blob}}]}]},
    )

    line = [r for r in caplog.records if r.name == "app.llm.wire"][-1].getMessage()
    assert "B" * 100 not in line
    assert "data URI 생략" in line


def test_llm_wire_keeps_long_prompt_text(caplog):
    """긴 컨텍스트(추천 후보 수백 건)는 절단하지 않는다 — 전문 보존이 목적."""
    caplog.set_level(logging.INFO, logger="app.llm.wire")
    long_prompt = "가맹점" * 5_000

    prompt_capture.capture_request("etribe", "https://llm/x", {"messages": [{"content": long_prompt}]})

    line = [r for r in caplog.records if r.name == "app.llm.wire"][-1].getMessage()
    assert long_prompt in line


# ── 로깅 부트스트랩 ────────────────────────────────────────────────────────────
def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    before = len(root.handlers)

    configure_logging("INFO")
    configure_logging("INFO")
    configure_logging("DEBUG")

    added = [h for h in root.handlers if getattr(h, "name", None) == "app-stdout"]
    assert len(added) == 1
    assert len(root.handlers) <= before + 1
    assert added[0].level == logging.DEBUG  # 재호출 시 레벨만 갱신.


def test_configure_logging_quiets_httpx_duplicate_lines():
    """httpx 의 요청 로그는 app.http.out 과 내용이 겹친다 — 중복 출력을 막는다."""
    configure_logging("INFO")

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


@pytest.mark.parametrize("level", ["", None, "NOPE"])
def test_configure_logging_unknown_level_falls_back_to_info(level):
    configure_logging(level)

    handler = next(h for h in logging.getLogger().handlers if getattr(h, "name", None) == "app-stdout")
    assert handler.level == logging.INFO
