"""expense_card.chat_form 통합 단위테스트 — wait_hitl 멀티턴 루프 + 도구 디스패치(모킹).

실 브라우저/실 Gemini 없이: page 는 FakePage(identity 라우팅), Gemini 판단은
`gemini_chat_decide` 를 스크립트 함수로 monkeypatch. app.live.hitl.resolve_hitl 로 사용자
메시지/‘선택 완료’를 주입한다. 저장(F7) 액션이 없음을 mouse.click 미발생으로 확인한다.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import app.agents.expense_card.chat_form as CF
import app.agents.expense_card.tools as T
from app.live.hitl import resolve_hitl


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class FakePage:
    def __init__(self, handler: Callable[[Any, Any], Any]) -> None:
        self._handler = handler
        self.mouse = _FakeMouse()

    async def evaluate(self, script: Any, arg: Any = None) -> Any:
        return self._handler(script, arg)

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def screenshot(self, **_kw: Any) -> bytes:
        return b"\xff\xd8\xff\xe0jpegbytes"


def _fake_settings(key: str) -> SimpleNamespace:
    return SimpleNamespace(gemini_api_key=key, gemini_model="m", gemini_base_url="http://b")


async def test_chat_form_errors_without_gemini_key(monkeypatch):
    monkeypatch.setattr(CF, "get_settings", lambda: _fake_settings(""))
    page = FakePage(lambda s, a: True)  # MODAL_IDLE → True
    events: asyncio.Queue = asyncio.Queue()
    out = await CF.make_chat_form_node()({"page": page, "events": events})
    assert "error" in out
    assert "GEMINI_API_KEY" in out["error"]


async def test_chat_form_loop_dispatches_fill_then_completes(monkeypatch):
    monkeypatch.setattr(CF, "get_settings", lambda: _fake_settings("x"))

    # 스크립트 Gemini: 첫 턴 → fill_text('적요','메모') → turn_done. (2호출)
    scripted = iter(
        [
            ("fill_text", {"field": "적요", "value": "메모"}),
            ("turn_done", {"message": "처리했어요"}),
        ]
    )

    async def fake_decide(*_a: Any, **_k: Any):
        return next(scripted)

    monkeypatch.setattr(CF, "gemini_chat_decide", fake_decide)

    def handler(script, arg):  # noqa: ANN001
        if script is CF.MODAL_IDLE_JS:
            return True
        if script is CF.CARD_FORM_SCHEMA_JS:
            return {"ok": True, "pickers": [], "drops": [], "inputs": []}
        if script is T.CARD_TEXT_SET_JS:
            return {"ok": True, "id": "note1"}
        return None

    page = FakePage(handler)
    events: asyncio.Queue = asyncio.Queue()
    frames: list[dict] = []
    sent = {"done": False}

    async def drain() -> None:
        # 단일 decision_id 로 멀티턴: 같은 큐에 메시지 → '선택 완료'를 순서대로 넣는다.
        while True:
            ev = await events.get()
            frames.append(ev)
            if "hitl" in ev and not sent["done"]:
                did = ev["hitl"]["id"]
                resolve_hitl(did, {"message": "적요 메모"})
                resolve_hitl(did, {"done": True})
                sent["done"] = True

    drain_task = asyncio.create_task(drain())
    try:
        out = await asyncio.wait_for(CF.make_chat_form_node(timeout_s=5)({"page": page, "events": events}), timeout=5)
    finally:
        drain_task.cancel()
    # 노드 완료 후 큐에 남은 프레임을 마저 수거(동시 drain 이 놓친 뒷부분).
    while not events.empty():
        frames.append(events.get_nowait())

    # 완료 결과(→ succeeded).
    assert "result" in out
    assert "대화형 폼 완료" in out["result"]
    assert "적요" in out["result"]

    # chat HITL 은 하나의 decision_id 로 한 번만 열린다(멀티턴은 같은 큐로).
    hitls = [f["hitl"] for f in frames if "hitl" in f]
    assert len(hitls) == 1
    assert hitls[0]["kind"] == "chat"

    # fill 액션이 chat 프레임으로 스트림됐다.
    chat_texts = [f["chat"]["content"] for f in frames if "chat" in f]
    assert any("적요" in c for c in chat_texts)

    # 저장(F7)·버튼 클릭이 전혀 없었다(fill_text/turn_done 경로는 좌표 클릭 없음).
    assert page.mouse.clicks == []


@pytest.mark.parametrize("bad_message", [{"message": ""}, {"message": "   "}])
async def test_chat_form_ignores_empty_then_completes(monkeypatch, bad_message):
    monkeypatch.setattr(CF, "get_settings", lambda: _fake_settings("x"))

    async def fake_decide(*_a: Any, **_k: Any):  # 빈 입력은 Gemini 까지 가지 않아야 함
        raise AssertionError("빈 메시지에 Gemini 를 호출하면 안 됨")

    monkeypatch.setattr(CF, "gemini_chat_decide", fake_decide)

    def handler(script, arg):  # noqa: ANN001
        if script is CF.MODAL_IDLE_JS:
            return True
        if script is CF.CARD_FORM_SCHEMA_JS:
            return {"ok": True, "pickers": [], "drops": [], "inputs": []}
        return None

    page = FakePage(handler)
    events: asyncio.Queue = asyncio.Queue()
    sent = {"done": False}

    async def drain() -> None:
        while True:
            ev = await events.get()
            if "hitl" in ev and not sent["done"]:
                did = ev["hitl"]["id"]
                resolve_hitl(did, bad_message)  # 빈 입력(무시돼야 함)
                resolve_hitl(did, {"done": True})
                sent["done"] = True

    drain_task = asyncio.create_task(drain())
    try:
        out = await asyncio.wait_for(CF.make_chat_form_node(timeout_s=5)({"page": page, "events": events}), timeout=5)
    finally:
        drain_task.cancel()
    assert "result" in out  # 빈 입력은 무시하고 다음 턴(완료)으로 진행
