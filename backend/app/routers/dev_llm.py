"""개발용 LLM 프로바이더 런타임 전환 라우터 — GET/PUT /dev/llm-provider.

로컬 dev 전용: settings.llm_provider_toggle(env LLM_PROVIDER_TOGGLE)이 꺼져 있으면 GET/PUT
모두 404 — 기능 자체가 존재하지 않는 것처럼 응답한다(서버 배포에서 FE 버튼 은닉의 근거이자
1차 방어). 권한은 로그인 사용자면 충분(admin 강제 불요 — 게이트 env 가 1차 방어).

오버라이드는 **프로세스 메모리**(app.core.llm_runtime 모듈 전역)에만 저장되며 재시작 시
env 기본으로 복귀한다 — 로컬 dev 용도로 의도된 동작. 전환은 이후의 모든 LLM 경로
(/assistant 스트림, 에이전트 디스패처 chat_decide/generate_text/llm_ready/llm_model_name)에
즉시 반영된다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.deps import CurrentUser
from app.core.llm_runtime import (
    effective_llm_provider,
    llm_provider_source,
    set_llm_provider_override,
)

def _gate() -> None:
    """게이트 off → 404: 기능 자체가 없는 것처럼 응답(서버 배포 보호).

    라우터 레벨 의존성이라 **인증(CurrentUser)·본문 검증보다 먼저** 실행된다 — 게이트 off
    서버에서 미인증 프로브가 401 을 받아 엔드포인트 존재가 노출되는 것을 막는다(리뷰 지적).
    메서드 미스매치 405 노출은 수용(상태 변경 불가·존재 힌트뿐이라 위험 미미)으로 문서화.
    """
    if not get_settings().llm_provider_toggle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(_gate)])


class LlmProviderIn(BaseModel):
    # Literal 이 미지 값을 422 로 걸러준다 — set_llm_provider_override 의 ValueError 는 2차 방어.
    provider: Literal["gemini", "etribe"]


def _state_payload(settings: Settings) -> dict:
    """GET/PUT 공통 응답 — 활성 프로바이더·판정 출처·선택지(라벨은 settings 모델명 동적)."""
    return {
        "active": effective_llm_provider(settings),
        "source": llm_provider_source(),
        "options": [
            {"id": "gemini", "label": f"Gemini ({settings.gemini_model})"},
            {"id": "etribe", "label": "Etribe-LLM (사내)"},
        ],
    }


@router.get("/llm-provider")
async def get_llm_provider(_actor: CurrentUser) -> dict:
    """현재 활성 LLM 프로바이더 상태 조회(로그인 사용자 전용)."""
    return _state_payload(get_settings())


@router.put("/llm-provider")
async def put_llm_provider(body: LlmProviderIn, _actor: CurrentUser) -> dict:
    """LLM 프로바이더 런타임 오버라이드 설정 — 이후 모든 LLM 경로에 즉시 반영.

    프로세스 메모리 오버라이드라 재시작 시 env 기본으로 복귀한다(로컬 dev 의도 동작).
    """
    set_llm_provider_override(body.provider)
    return _state_payload(get_settings())
