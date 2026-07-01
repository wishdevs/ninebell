"""demo-echo — P2 더미 워크플로우(실 옴니솔 불필요).

fresh 헤드리스 브라우저를 띄워 about:blank 에 간단한 HTML 을 심고, 스크린캐스트 프레임 +
step/log/chat + HITL(확인) 한 번 + result 를 방출한다. 이걸로 `/runs/collect` SSE·커서
재접속·스크린캐스트·`/runs/hitl` 왕복을 실 워크플로우 없이 검증한다. P3 워크플로우
(expense-card-chat 등)가 따를 그래프 템플릿이기도 하다.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.config import get_settings

from .events import emit_chat, emit_log, emit_step
from .hitl import wait_hitl


class DemoState(TypedDict, total=False):
    page: Any  # Playwright Page(있을 수 있음). 없으면 브라우저 조작을 건너뛴다.
    events: Any  # asyncio.Queue
    userid: str | None
    password: str | None
    params: dict
    result: str
    error: str


_PAGE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#0b1020;color:#e6ecff;
display:flex;align-items:center;justify-content:center;height:100vh}}
.card{{text-align:center}}.h{{font-size:40px;font-weight:700;letter-spacing:-1px}}
.s{{margin-top:10px;color:#8aa0d0;font-size:16px}}.t{{margin-top:20px;color:#5f7bd0}}</style></head>
<body><div class="card"><div class="h">demo-echo</div>
<div class="s">{msg}</div><div class="t">{ts}</div></div></body></html>"""


async def _set_screen(page: Any, msg: str) -> None:
    """데모 화면 갱신(스크린캐스트가 변화를 프레임으로 잡도록). page 없으면 무시."""
    if page is None:
        return
    try:
        html = _PAGE_HTML.format(msg=msg, ts=time.strftime("%H:%M:%S"))
        await page.set_content(html)
    except Exception:
        pass


def _node_open():
    async def open_page(state: DemoState) -> dict:
        events = state["events"]
        page = state.get("page")
        await emit_step(events, "브라우저 시작", "running")
        if page is not None:
            try:
                await page.goto("about:blank")
            except Exception:
                pass
        await _set_screen(page, "라이브 세션이 시작되었습니다.")
        await asyncio.sleep(0.4)  # 스크린캐스트 프레임 확보
        await emit_log(events, "헤드리스 브라우저를 준비했습니다.", "ok")
        await emit_step(events, "브라우저 시작", "done")
        return {}

    return open_page


def _node_greet():
    async def greet(state: DemoState) -> dict:
        events = state["events"]
        page = state.get("page")
        await emit_step(events, "인사", "running")
        await emit_chat(
            events,
            chat_id=uuid.uuid4().hex,
            role="assistant",
            content="안녕하세요! demo-echo 워크플로우입니다. 계속 진행할까요?",
            streaming=False,
            done=True,
        )
        await _set_screen(page, "사용자 확인을 기다리는 중…")
        await asyncio.sleep(0.4)
        await emit_step(events, "인사", "done")
        return {}

    return greet


def _node_confirm():
    async def confirm(state: DemoState) -> dict:
        events = state["events"]
        page = state.get("page")
        await emit_step(events, "사용자 확인", "running")
        s = get_settings()
        try:
            payload = await wait_hitl(
                events,
                kind="confirm",
                title="계속 진행",
                prompt="demo-echo 를 계속 진행하시겠어요?",
                options=[
                    {"value": "yes", "label": "예, 계속"},
                    {"value": "no", "label": "아니요"},
                ],
                timeout_s=s.hitl_timeout_s,
            )
        except asyncio.TimeoutError:
            await emit_step(events, "사용자 확인", "failed")
            return {"error": "확인 대기 시간이 초과되었습니다."}
        choice = (payload.get("value") or payload.get("message") or "").strip()
        await _set_screen(page, f"사용자 선택: {choice or '(없음)'}")
        await asyncio.sleep(0.3)
        await emit_log(events, f"사용자 선택: {choice or '(없음)'}", "info")
        await emit_step(events, "사용자 확인", "done")
        return {"result": choice}

    return confirm


def _node_finish():
    async def finish(state: DemoState) -> dict:
        events = state["events"]
        if state.get("error"):
            return {}
        choice = state.get("result") or ""
        await emit_step(events, "완료", "done")
        return {"result": f"demo-echo 완료 — 선택: {choice or '(없음)'}"}

    return finish


def build_demo_echo_graph():
    """demo-echo LangGraph 컴파일 그래프를 만든다(P3 워크플로우 템플릿)."""
    g = StateGraph(DemoState)
    g.add_node("open", _node_open())
    g.add_node("greet", _node_greet())
    g.add_node("confirm", _node_confirm())
    g.add_node("finish", _node_finish())
    g.set_entry_point("open")
    g.add_edge("open", "greet")
    g.add_edge("greet", "confirm")
    g.add_edge("confirm", "finish")
    g.add_edge("finish", END)
    return g.compile()
