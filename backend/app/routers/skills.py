"""스킬 카탈로그 라우터 — GET /skills.

app/services/skills.py 카탈로그(단일 소스)에 AgentStep.skill(=키) 역인덱스를
결합해 "이 스킬을 어떤 에이전트가 쓰는가"를 함께 내려준다. 인증 필요(CurrentUser).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import Agent, AgentStep
from app.services.skills import SKILLS

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills(user: CurrentUser, db: DbSession) -> dict:
    """스킬 카탈로그 + 스킬별 사용 에이전트 역인덱스.

    응답: {items: [{key, label, description, layer, agents: [{id, name}]}]}
    (카탈로그 정의 순서 고정 — 에이전트는 id 오름차순.)
    """
    rows = await db.execute(
        select(AgentStep.skill, Agent.id, Agent.name)
        .join(Agent, Agent.id == AgentStep.agent_id)
        .where(AgentStep.skill.is_not(None))
        .distinct()
    )
    agents_by_skill: dict[str, list[dict]] = {}
    for skill_key, agent_id, agent_name in rows:
        agents_by_skill.setdefault(skill_key, []).append({"id": agent_id, "name": agent_name})

    items = [
        {
            "key": skill.key,
            "label": skill.label,
            "description": skill.description,
            "layer": skill.layer,
            "agents": sorted(agents_by_skill.get(skill.key, []), key=lambda a: a["id"]),
        }
        for skill in SKILLS.values()
    ]
    return {"items": items}
