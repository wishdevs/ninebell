"""이벤트 프레임 헬퍼 — 프론트(P4) SSE 계약과 1:1 매핑.

프레임은 모두 평탄한 dict 이며 SSE 로 그대로 직렬화된다(FE 는 `data.step`/`data.log`/
`data.screenshot`/`data.hitl`/`data.chat`/`data.transactions`/`data.result`/`data.error`
를 읽는다). 워크플로우 노드는 `state["events"]`(asyncio.Queue)로 이 헬퍼를 통해 방출한다.

프레임 계약(고정):
    {"step": str, "status": "running"|"done"|"failed", "ms"?: int}
    {"log": str, "level": "info"|"ok"|"error"|"warn"}
    {"screenshot": "data:image/jpeg;base64,..."}          # 비버퍼(최신 1장)
    {"hitl": {"id","kind","title","prompt","options"?}}
    {"chat": {"id","role","content","streaming"?,"done"?,"note"?}}
    {"transactions": {"title","columns","rows"}}
    {"result": str}                                        # 종료(성공)
    {"error": str}                                         # 종료(실패)
"""

from __future__ import annotations

import asyncio


async def emit_step(events: asyncio.Queue, step: str, status: str, ms: int | None = None) -> None:
    ev: dict = {"step": step, "status": status}
    if ms is not None:
        ev["ms"] = ms
    await events.put(ev)


async def emit_log(events: asyncio.Queue, message: str, level: str = "info") -> None:
    await events.put({"log": message, "level": level})


async def emit_screenshot(events: asyncio.Queue, data_url: str) -> None:
    """단발 스냅샷(스크린캐스트와 별개). data_url 은 'data:image/jpeg;base64,...' 형식."""
    await events.put({"screenshot": data_url})


async def emit_hitl(
    events: asyncio.Queue,
    *,
    decision_id: str,
    kind: str,
    title: str,
    prompt: str,
    options: list[dict] | None = None,
    **extra,
) -> None:
    frame: dict = {"id": decision_id, "kind": kind, "title": title, "prompt": prompt}
    if options:
        frame["options"] = options
    if extra:
        frame.update(extra)
    await events.put({"hitl": frame})


async def emit_chat(
    events: asyncio.Queue,
    *,
    chat_id: str,
    role: str,
    content: str,
    streaming: bool | None = None,
    done: bool | None = None,
    note: str | None = None,
) -> None:
    frame: dict = {"id": chat_id, "role": role, "content": content}
    if streaming is not None:
        frame["streaming"] = streaming
    if done is not None:
        frame["done"] = done
    if note is not None:
        frame["note"] = note
    await events.put({"chat": frame})


async def emit_transactions(
    events: asyncio.Queue, *, title: str, columns: list, rows: list
) -> None:
    await events.put({"transactions": {"title": title, "columns": columns, "rows": rows}})


async def emit_result(events: asyncio.Queue, result: str) -> None:
    await events.put({"result": result})


async def emit_error(events: asyncio.Queue, error: str) -> None:
    await events.put({"error": error})
