"""에이전트 라우터 — GET /agents, GET /agents/{id}. agents:read 게이트.
PATCH /agents/{id}/settings 는 관리자(admin+) 전용 세부설정 저장.

조직접근 가시성: 실행 게이트(runs.py)와 동일 규칙으로 user 롤에게는 접근 가능한
에이전트만 노출한다(목록=제외, 상세=404 로 존재 자체 숨김). admin+ 는 전체.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.deps import DbSession, RequireAdmin, require_permission
from app.core.permissions import AGENTS_READ
from sqlalchemy import select

from app.models import Agent, AgentGroup, User
from app.services.agent_fixtures import AGENT_FIXTURES
from app.services.agent_settings import validate_settings
from app.services.agent_visibility import (
    HIDDEN_AGENT_IDS,
    accessible_agent_ids,
    accessible_group_ids,
    is_org_admin,
    is_visible,
    visible_agents,
)
from app.services.agents import compute_run_stats, serialize_agent
from app.services.step_timings import expected_step_ms

# 표시 순서 = 픽스처 정의 순서(의도된 순서). created_at 은 배치 시드 시 동일값이라 타이브레이크가
# 비결정적(예: 결의서입력 그룹의 출장/경조금/학자금이 임의 순서). 픽스처에 없는 에이전트는 뒤로.
_FIXTURE_ORDER: dict[str, int] = {f["id"]: i for i, f in enumerate(AGENT_FIXTURES)}

# 숨김 에이전트 — 단일 소스는 services.agent_visibility.HIDDEN_AGENT_IDS. 모듈 전역 별칭은
# 테스트 주입 앵커(test_agent_run_stats.py 가 monkeypatch) — 핸들러가 호출 시점에 이 전역을 읽는다.
_HIDDEN_AGENT_IDS: frozenset[str] = HIDDEN_AGENT_IDS

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(
    db: DbSession,
    actor: Annotated[User, Depends(require_permission(AGENTS_READ))],
) -> list[dict]:
    # 숨김 제외 + user 롤 조직접근 필터 — runs 실행 게이트와 동일 소스(services.agent_visibility).
    rows = await visible_agents(db, actor, hidden_ids=_HIDDEN_AGENT_IDS)
    # 픽스처 정의 순서로 정렬(카드 → 출장 국내). 픽스처 밖은 뒤로 + 시각순.
    rows.sort(key=lambda a: (_FIXTURE_ORDER.get(a.id, len(_FIXTURE_ORDER)), a.created_at))
    # ⚠ agent_runs.agent_id 에는 **workflow_id** 가 저장된다(models/agent_run.py 주석) —
    #   Agent.id(PK) 로 집계하면 영원히 0 이다(회귀 2026-08-10: voucher 그룹 통계 미표시).
    stats = await compute_run_stats(db, [a.workflow_id for a in rows if a.workflow_id])
    return [
        serialize_agent(a, stats=stats.get(a.workflow_id) if a.workflow_id else None)
        for a in rows
    ]


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
    if not is_org_admin(actor):
        allowed_ids = await accessible_agent_ids(db, actor)
        # 그룹 게이트 AND 에이전트 게이트(2026-08-31) — 목록(visible_agents)과 동일 판정식.
        allowed_group_ids = await accessible_group_ids(db, actor)
        groups_by_id = {g.id: g for g in (await db.execute(select(AgentGroup))).scalars()}
        if not is_visible(agent, actor, allowed_ids, allowed_group_ids, groups_by_id):
            # 접근 불가 에이전트는 존재 자체를 숨긴다(목록 제외와 일관).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다."
            )
    # 상세에서만 단계별 예상 소요(최근 성공 런 실측 평균) 계산 — 목록은 부하상 미계산.
    step_ms = await expected_step_ms(db, agent.workflow_id) if agent.workflow_id else None
    # 런 이력 키는 workflow_id — 목록 집계와 동일(2026-08-10).
    stats = await compute_run_stats(db, [agent.workflow_id]) if agent.workflow_id else {}
    return serialize_agent(
        agent, stats=stats.get(agent.workflow_id), include_flow=True, step_expected_ms=step_ms
    )


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
    # 런 이력 키는 workflow_id — 목록/상세 집계와 동일(2026-08-10).
    stats = await compute_run_stats(db, [agent.workflow_id]) if agent.workflow_id else {}
    return serialize_agent(agent, stats=stats.get(agent.workflow_id))
