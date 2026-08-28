"""사용자 확인 개입(kind 'confirm') 공용 — 비가역 동사(저장·상신) 직전에 한 번 묻는다.

헤디드 실행에서 사용자가 브라우저를 직접 보며 판단하는 게이트다(사용자 지시 2026-08-28).
프레임: {"hitl": {"id","kind":"confirm","title","prompt","options":[{value,label}...]}} — 프론트
LiveChoiceCard 가 단일 선택 즉시 제출({value}). 응답 value 를 돌려주며, 타임아웃은 None.
"""

from __future__ import annotations

import asyncio
import uuid

from app.config import get_settings
from app.live.events import emit_hitl
from app.live.hitl import close_hitl_channel, open_hitl_channel

CONFIRM_TIMEOUT_S = 1800


async def ask_confirm(
    state: dict, *, title: str, prompt: str, options: list[dict], timeout_s: int | None = None
) -> str | None:
    """confirm HITL 을 띄우고 선택 value 를 돌려준다(타임아웃/무응답 None)."""
    events = state["events"]
    decision_id = uuid.uuid4().hex
    q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))
    cap = timeout_s or getattr(get_settings(), "hitl_timeout_s", CONFIRM_TIMEOUT_S)
    try:
        await emit_hitl(
            events, decision_id=decision_id, kind="confirm", title=title, prompt=prompt, options=options
        )
        while True:
            try:
                resp = await asyncio.wait_for(q.get(), timeout=cap)
            except (TimeoutError, asyncio.TimeoutError):
                return None
            value = resp.get("value") if isinstance(resp, dict) else None
            if value is None:
                continue
            return str(value)
    finally:
        close_hitl_channel(decision_id)
