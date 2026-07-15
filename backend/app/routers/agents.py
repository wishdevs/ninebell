"""에이전트 라우터 — GET /agents, GET /agents/{id}. agents:read 게이트.
PATCH /agents/{id}/settings 는 관리자(admin+) 전용 세부설정 저장.

조직접근 가시성: 실행 게이트(runs.py)와 동일 규칙으로 user 롤에게는 접근 가능한
에이전트만 노출한다(목록=제외, 상세=404 로 존재 자체 숨김). admin+ 는 전체.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import DbSession, require_permission, require_role_min
from app.core.permissions import AGENTS_READ, ROLE_ADMIN, ROLE_RANK, role_rank
from app.models import Agent, AgentOrgAccess, User
from app.services.agent_fixtures import AGENT_FIXTURES
from app.services.agent_settings import validate_settings
from app.services.agents import compute_run_stats, serialize_agent
from app.services.step_timings import expected_step_ms

# 표시 순서 = 픽스처 정의 순서(의도된 순서). created_at 은 배치 시드 시 동일값이라 타이브레이크가
# 비결정적(예: 결의서입력 그룹의 출장/경조금/학자금이 임의 순서). 픽스처에 없는 에이전트는 뒤로.
_FIXTURE_ORDER: dict[str, int] = {f["id"]: i for i, f in enumerate(AGENT_FIXTURES)}

# 숨김 에이전트(hidden=True) — 목록/상세에서 완전히 제외한다(현재 숨김 대상 0 — 전 에이전트 노출.
# 메커니즘은 유지: 향후 hidden=True 픽스처가 생기면 자동 적용). DB 행·워크플로우 등록은 유지하되
# UI 도달을 막는다(직접 URL 도 404). 픽스처 플래그가 단일 소스.
_HIDDEN_AGENT_IDS: frozenset[str] = frozenset(f["id"] for f in AGENT_FIXTURES if f.get("hidden"))

router = APIRouter(prefix="/agents", tags=["agents"])

RequireAdmin = Annotated[User, Depends(require_role_min(role_rank(ROLE_ADMIN)))]


def _is_org_admin(user: User) -> bool:
    role_code = user.role.code if user.role is not None else None
    return role_rank(role_code) >= ROLE_RANK[ROLE_ADMIN]


async def _accessible_agent_ids(db: DbSession, user: User) -> set[str]:
    """user 소속 조직구분이 명시 허용된 agent id 집합(미지정 사용자는 빈 집합)."""
    if not user.org_unit_id:
        return set()
    rows = await db.execute(
        select(AgentOrgAccess.agent_id).where(AgentOrgAccess.org_unit_id == user.org_unit_id)
    )
    return set(rows.scalars())


def _visible(agent: Agent, user: User, allowed_ids: set[str]) -> bool:
    if not agent.access_configured:
        return True  # 최초(미설정) = 전체 허용.
    if not user.org_unit_id:
        return agent.allow_unassigned
    return agent.id in allowed_ids


@router.get("")
async def list_agents(
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(AGENTS_READ))],
) -> list[dict]:
    rows = list((await db.execute(select(Agent).order_by(Agent.created_at.asc()))).scalars().all())
    # 숨김 에이전트(hidden=True) 제외 — 현재 숨김 대상 0(전 에이전트 노출), 메커니즘만 유지.
    rows = [a for a in rows if a.id not in _HIDDEN_AGENT_IDS]
    # 픽스처 정의 순서로 정렬(카드 → 출장 국내). 픽스처 밖은 뒤로 + 시각순.
    rows.sort(key=lambda a: (_FIXTURE_ORDER.get(a.id, len(_FIXTURE_ORDER)), a.created_at))
    if not _is_org_admin(actor):
        allowed_ids = await _accessible_agent_ids(db, actor)
        rows = [a for a in rows if _visible(a, actor, allowed_ids)]
    stats = await compute_run_stats(db, [a.id for a in rows])
    return [serialize_agent(a, stats=stats.get(a.id)) for a in rows]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(AGENTS_READ))],
) -> dict:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent_id in _HIDDEN_AGENT_IDS:
        # 숨김 에이전트는 존재 자체를 숨긴다(직접 URL 접근도 404 = 비활성).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다.")
    if not _is_org_admin(actor):
        allowed_ids = await _accessible_agent_ids(db, actor)
        if not _visible(agent, actor, allowed_ids):
            # 접근 불가 에이전트는 존재 자체를 숨긴다(목록 제외와 일관).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다."
            )
    # 상세에서만 단계별 예상 소요(최근 성공 런 실측 평균) 계산 — 목록은 부하상 미계산.
    step_ms = await expected_step_ms(db, agent.workflow_id) if agent.workflow_id else None
    stats = await compute_run_stats(db, [agent.id])
    return serialize_agent(agent, stats=stats.get(agent.id), include_flow=True, step_expected_ms=step_ms)


class SettingsPatchIn(BaseModel):
    settings: dict


@router.patch("/{agent_id}/settings")
async def patch_agent_settings(
    agent_id: str, body: SettingsPatchIn, db: DbSession, _actor: RequireAdmin
) -> dict:
    """에이전트 세부설정 저장(관리자+). 스키마(코드 선언) 검증 후 저장값에 병합한다.

    스키마에 없는 키·타입/범위 위반은 400(한국어 메시지), 없는 에이전트는 404.
    """
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다.")
    try:
        validated = validate_settings(agent_id, body.settings)
    except ValueError as e:  # 스키마 없음 포함 — 메시지를 그대로 노출(한국어).
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    # 기존 저장값 위에 병합(불변 갱신 — JSON 컬럼 in-place 변경은 dirty 감지가 안 된다).
    agent.settings = {**(agent.settings or {}), **validated}
    await db.commit()
    stats = await compute_run_stats(db, [agent.id])
    return serialize_agent(agent, stats=stats.get(agent.id))
