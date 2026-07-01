"""에이전트 라우터 — GET /agents, GET /agents/{id}. agents:read 게이트."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import DbSession, require_permission
from app.core.permissions import AGENTS_READ
from app.models import Agent, User
from app.services.agents import serialize_agent

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(AGENTS_READ))],
) -> list[dict]:
    rows = (await db.execute(select(Agent).order_by(Agent.created_at.asc()))).scalars().all()
    return [serialize_agent(a) for a in rows]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(AGENTS_READ))],
) -> dict:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다.")
    return serialize_agent(agent, include_flow=True)
