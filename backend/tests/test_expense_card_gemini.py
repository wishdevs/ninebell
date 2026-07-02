"""expense_card.gemini 단위테스트 — 판단 호출의 retry+backoff(실 Gemini 미사용).

FakeHttp 가 httpx.Response 를 순서대로 반환한다(429/404/200 시나리오). backoff 는 0 으로
monkeypatch 해 즉시 진행. 폐기 모델(404+바디)은 재시도 없이 즉시 실패해야 한다.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import app.agents.expense_card.gemini as GM


def _resp(status: int, payload: dict | None = None, text: str = "") -> httpx.Response:
    req = httpx.Request("POST", "http://gemini.test/models/m:generateContent")
    if payload is not None:
        return httpx.Response(status, request=req, content=json.dumps(payload).encode())
    return httpx.Response(status, request=req, text=text)


class FakeHttp:
    """post 가 미리 지정한 httpx.Response 를 순서대로 반환하는 최소 클라이언트."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, url: str, headers: Any = None, json: Any = None) -> httpx.Response:
        self.calls += 1
        return self._responses.pop(0)


_FC_OK = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "ask", "args": {"question": "q"}}}]}}]}


async def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(GM, "_MAX_BACKOFF_S", 0.0)
    http = FakeHttp([_resp(429, text="rate limit"), _resp(200, _FC_OK)])
    name, args = await GM.gemini_chat_decide(http, "k", "m", "http://b", "sys", "hist", {}, None, [])
    assert name == "ask"
    assert args == {"question": "q"}
    assert http.calls == 2  # 429 1회 후 재시도 성공


async def test_retries_exhaust_then_raises(monkeypatch):
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(GM, "_MAX_BACKOFF_S", 0.0)
    http = FakeHttp([_resp(429), _resp(429), _resp(429)])
    with pytest.raises(httpx.HTTPStatusError):
        await GM.gemini_chat_decide(http, "k", "m", "http://b", "sys", "hist", {}, None, [])
    assert http.calls == GM._MAX_ATTEMPTS  # 최대 시도까지 소진


async def test_404_with_body_fails_fast_no_retry(monkeypatch):
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    # 폐기 모델: 404 + 바디('no longer available') → 재시도 무의미, 즉시 실패.
    http = FakeHttp([_resp(404, text="models/gemini-2.0-flash is no longer available")])
    with pytest.raises(httpx.HTTPStatusError):
        await GM.gemini_chat_decide(http, "k", "m", "http://b", "sys", "hist", {}, None, [])
    assert http.calls == 1  # 재시도 없음


async def test_network_error_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(GM, "_BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(GM, "_MAX_BACKOFF_S", 0.0)

    class FlakyHttp:
        def __init__(self) -> None:
            self.calls = 0

        async def post(self, url: str, headers: Any = None, json: Any = None) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("boom")
            return _resp(200, _FC_OK)

    http = FlakyHttp()
    name, _args = await GM.gemini_chat_decide(http, "k", "m", "http://b", "sys", "hist", {}, None, [])
    assert name == "ask"
    assert http.calls == 2


async def test_no_function_call_returns_none(monkeypatch):
    http = FakeHttp([_resp(200, {"candidates": [{"content": {"parts": [{"text": "no tool"}]}}]})])
    name, args = await GM.gemini_chat_decide(http, "k", "m", "http://b", "sys", "hist", {}, None, [])
    assert name is None
    assert args == {}
