"""AI 어시스턴트 라우터 — POST /assistant/chat (SSE 스트리밍).

로그인한 모든 사용자가 사용한다(별도 권한 없음 — /agents·/runs 읽기는 모든 롤의 암묵
권한). 미인증이면 스트림 시작 전에 401. 프로바이더는 스트림 제너레이터 *안*에서 지연
생성해, 키 누락 등 구성 오류가 500 이 아니라 종료 SSE 에러 프레임으로 표면화되게 한다.

프레임 계약: data: {"delta":"..."} / {"action":{...}} / {"error":"..."} / [DONE].
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.core.deps import CurrentUser
from app.llm.base import ChatMessage, LLMProvider
from app.llm.gemini import GeminiProvider
from app.schemas.assistant import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])

# 브라우저에 그대로 노출해도 안전한(로컬 개발 진단용) 구성 오류 마커. 그 외(업스트림 URL·
# 내부 예외)는 일반화해 절대 유출하지 않는다.
_CONFIG_ERROR_MARKERS = ("GEMINI_API_KEY",)
_GENERIC_STREAM_ERROR = "AI 어시스턴트 응답 생성 중 오류가 발생했습니다."


def _stream_error_message(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        text = str(exc)
        if any(marker in text for marker in _CONFIG_ERROR_MARKERS):
            return text
    return _GENERIC_STREAM_ERROR


ASSISTANT_SYSTEM = """\
당신은 '나인벨 업무 자동화 대시보드'의 AI 어시스턴트입니다.
역할: 사내 업무 자동화 대시보드의 대화형 안내자이자 운영 보조자입니다.
- 사용 가능한 에이전트(agents)와 실행(runs)에 대해 설명하고 질문에 답합니다.
- 아래 컨텍스트로 전달된 에이전트/실행 목록만을 사실 근거로 사용합니다. 모르면 모른다고 답합니다.
도구(함수) 사용 — 사용자의 의도를 의미로 추론해(키워드 매칭이 아니라) 적절히 호출하라:
- 사용자가 특정 에이전트를 보거나/실행하거나/그 정보를 원하는 의도면 suggest_agent(agentId, intent) 를 호출.
- 사용자가 특정 실행(run)을 보고 싶어하는 의도면 suggest_run(runId) 를 호출.
- agentId/runId 는 반드시 아래 컨텍스트의 agents[].id / runs[].id 중 하나여야 한다. 확실치 않으면 호출하지 마라.
- 함수 호출과 함께, 무엇을 안내하는지 한 줄 정도의 짧은 한국어 설명도 덧붙여라.
한국어로, 간결하고 정확하게 답하세요."""


# 어시스턴트가 호출할 수 있는 도구(의도 → 액션). 프론트가 이 호출을 네비게이션 카드로 렌더한다.
ASSISTANT_TOOLS = [
    {
        "name": "suggest_agent",
        "description": (
            "사용자가 특정 에이전트를 보거나, 그에 대해 묻거나, 실행을 원하는 것으로 "
            "판단되면 호출한다. agentId 는 반드시 컨텍스트 agents[].id 중 하나."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agentId": {"type": "string", "description": "컨텍스트 agents[].id"},
                "intent": {
                    "type": "string",
                    "enum": ["open", "run", "info"],
                    "description": "사용자 의도: 열기/실행/정보",
                },
            },
            "required": ["agentId"],
        },
    },
    {
        "name": "suggest_run",
        "description": "사용자가 특정 실행(run)을 보고 싶어하면 호출. runId 는 컨텍스트 runs[].id 중 하나.",
        "parameters": {
            "type": "object",
            "properties": {"runId": {"type": "string", "description": "컨텍스트 runs[].id"}},
            "required": ["runId"],
        },
    },
]


def build_llm(request: Request, settings: Settings) -> LLMProvider:
    """스트림 제너레이터 안에서 지연 호출된다 — 키 누락은 여기서 RuntimeError 로 표면화."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않아 AI 어시스턴트를 사용할 수 없습니다.")
    return GeminiProvider(
        request.app.state.http,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
    )


def _system_prompt(req: ChatRequest) -> str:
    parts = [ASSISTANT_SYSTEM]
    if req.system:
        parts.append(req.system)
    if req.context:
        parts.append("## 현재 사용 가능한 컨텍스트(JSON)\n" + json.dumps(req.context, ensure_ascii=False))
    return "\n\n".join(parts)


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, _actor: CurrentUser) -> StreamingResponse:
    settings = get_settings()
    system = _system_prompt(req)
    msgs = [ChatMessage(role=m.role, content=m.content) for m in req.messages]

    # 사용자당 동시 스트림·최소 요청 간격 제한 — 유료 Gemini API 남용 방지. 스트림 시작 전
    # 거부되므로 429 로 즉시 응답한다(SSE 프레임이 아니라 일반 HTTP 오류).
    limiter = request.app.state.assistant_limiter
    user_key = str(_actor.id)
    deny_reason = limiter.try_acquire(user_key)
    if deny_reason is not None:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=deny_reason)

    async def event_stream():
        try:
            # 프로바이더를 스트림 안에서 지연 생성 — 키 누락(또는 생성 실패)이 500 대신
            # 종료 SSE 에러 프레임으로 표면화된다(Depends() 는 이 try/except 전에 raise).
            llm = build_llm(request, settings)
            async for chunk in llm.chat(
                msgs,
                system=system,
                temperature=req.temperature,
                max_output_tokens=req.max_output_tokens,
                tools=ASSISTANT_TOOLS,
            ):
                if chunk.delta:
                    yield f"data: {json.dumps({'delta': chunk.delta}, ensure_ascii=False)}\n\n"
                if chunk.tool_call:
                    yield f"data: {json.dumps({'action': chunk.tool_call}, ensure_ascii=False)}\n\n"
                if chunk.done:
                    yield "data: [DONE]\n\n"
        except Exception as exc:  # 실패를 종료 SSE 에러 프레임으로 표면화
            logger.exception("assistant chat stream failed")
            message = _stream_error_message(exc)
            yield f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            limiter.release(user_key)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
