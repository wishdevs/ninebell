"""라이브 실행(run) 라우터 — SSE 수집 + HITL 응답.

POST /runs/collect: 워크플로우를 라이브 세션으로 실행하고 단계 이벤트를 SSE 로 스트리밍한다.
  세션이 SSE 연결과 분리돼 살아있으므로(app.live.session), 끊김 뒤 같은 runId+cursor 로
  재부착하면 흐름을 재시작하지 않고 커서 이후만 재생한다. 인증은 세션 쿠키(get_current_user).
POST /runs/hitl: 라이브 흐름의 HITL 대기에 사용자 응답을 전달한다(소유자=현재 유저 검증).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser
from app.live import store
from app.live.hitl import hitl_owner, resolve_hitl
from app.live.registry import get_workflow
from app.live.runner import run_workflow
from app.live.session import create_session, get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])


def _sse(events) -> StreamingResponse:
    """이벤트 dict 비동기 이터러블을 SSE(text/event-stream) 응답으로 감싼다."""

    async def body():
        async for ev in events:
            # default=str: 날짜(datetime) 등 비직렬화 값을 문자열로.
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class CollectRequest(BaseModel):
    # 서버 세션/런 id(세션 사용자 소유). 있으면 재연결·런 추적, 없으면 익명(1회성).
    runId: str | None = Field(default=None, max_length=40)
    agentId: str = Field(default="demo-echo", max_length=64)
    # 재연결(resume) 커서 — 이미 받은 이벤트 수. >0 이면 기존 세션 재부착(새 흐름 시작 안 함).
    cursor: int = Field(default=0, ge=0)
    # 워크플로우 파라미터(그래프 state["params"] 로 주입).
    params: dict | None = None


class HitlDecision(BaseModel):
    runId: str | None = Field(default=None, max_length=40)
    decisionId: str = Field(min_length=1, max_length=64)
    value: str | None = Field(default=None, max_length=100)
    values: list[str] | None = None
    text: str | None = Field(default=None, max_length=500)
    query: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=2000)  # 대화형 HITL 한 턴 자연어
    done: bool | None = None  # 대화형 폼 '선택 완료' 신호


def _browser_factory(request: Request):
    """fresh 헤드리스 브라우저를 여는 async 콜러블. 테스트는 app.state override 로 주입."""
    override = getattr(request.app.state, "browser_factory", None)
    if override is not None:
        return override
    pw = request.app.state.playwright

    async def factory():
        return await pw.chromium.launch(headless=True)

    return factory


@router.post("/collect")
async def collect(body: CollectRequest, request: Request, user: CurrentUser):
    """워크플로우를 라이브 세션으로 실행하고 단계 이벤트를 SSE 로 스트리밍(재연결 지원)."""
    owner = str(user.id)

    # 재연결(resume): 같은 runId 세션이 살아있으면 흐름을 재시작하지 않고 커서 이후만 재생.
    sess = get_session(body.runId)
    if sess is not None:
        if sess.owner and sess.owner != owner:
            return JSONResponse({"error": "이 흐름에 대한 권한이 없습니다."}, status_code=403)
        return _sse(sess.stream(body.cursor))

    # 세션이 없는데 커서>0 → 흐름이 이미 종료/정리됨(새 브라우저를 띄우지 않는다).
    if body.runId and body.cursor > 0:
        return JSONResponse(
            {"error": "흐름이 종료되었습니다. 다시 실행해 주세요."}, status_code=410
        )

    factory = get_workflow(body.agentId)
    if factory is None:
        return JSONResponse(
            {"error": f"알 수 없는 워크플로우입니다: {body.agentId}"}, status_code=404
        )

    tracked_run_id = body.runId
    if tracked_run_id:
        # 재추적: 다른 사용자의 런 id 면 차단(소유 격리).
        existing = await store.get_run(tracked_run_id)
        if existing is not None and str(existing.user_id) != owner:
            return JSONResponse({"error": "런을 찾을 수 없습니다."}, status_code=404)
        await store.create_run(run_id=tracked_run_id, agent_id=body.agentId, user_id=user.id)

    browser_factory = _browser_factory(request)
    semaphore = getattr(request.app.state, "erp_semaphore", None)
    # P3 가 세션 자격증명(비밀번호)을 주입한다. P2 더미(demo-echo)는 자격증명을 쓰지 않는다.
    creds = {"userid": user.omnisol_userid, "password": None}
    params = body.params or {}

    def producer():
        return run_workflow(factory(), browser_factory, creds, params, semaphore=semaphore)

    async def on_terminal(status: str, note: str | None, logs: list) -> None:
        if tracked_run_id:
            await store.set_terminal(tracked_run_id, status, note, logs)

    sess = create_session(body.runId, owner, producer, on_terminal)
    return _sse(sess.stream(0))


@router.post("/hitl")
async def hitl(body: HitlDecision, user: CurrentUser):
    """라이브 흐름의 HITL 대기에 사용자 응답 전달. 세션이 소유한 HITL 은 같은 사용자만 가능."""
    owner = hitl_owner(body.decisionId)
    if owner is not None and owner != str(user.id):
        return JSONResponse(
            {"ok": False, "error": "이 HITL 에 대한 권한이 없습니다."}, status_code=403
        )
    payload = {
        "value": body.value,
        "values": body.values,
        "text": body.text,
        "query": body.query,
        "message": body.message,
        "done": body.done,
    }
    return {"ok": resolve_hitl(body.decisionId, payload)}
