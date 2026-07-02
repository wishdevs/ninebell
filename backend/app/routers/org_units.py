"""조직구분 관리 + 에이전트 접근 관리 라우터 (관리자+).

- /org-units       : 조직구분 CRUD + 순서변경.
- /agent-access    : 에이전트별 사용 가능 조직구분 조회/설정.
'최초 모두 선택' = agents.access_configured=false 이면 GET 이 전체 조직구분을 반환. PATCH 시
명시 행으로 교체하고 access_configured=true. 응답은 프론트 규약대로 camelCase.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.core.deps import DbSession, require_role_min
from app.core.permissions import ROLE_ADMIN, role_rank
from app.models import Agent, AgentOrgAccess, OrgUnit, User

router = APIRouter(tags=["org-units"])

RequireAdmin = Annotated[User, Depends(require_role_min(role_rank(ROLE_ADMIN)))]


# ── 스키마 ────────────────────────────────────────────────────────────────────
class OrgUnitCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class OrgUnitUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class ReorderIn(BaseModel):
    orderedIds: list[str]


class AgentAccessSetIn(BaseModel):
    orgUnitIds: list[str]


def _org_dict(o: OrgUnit) -> dict:
    return {"id": o.id, "label": o.label, "sortOrder": o.sort_order}


# ── 조직구분 CRUD ─────────────────────────────────────────────────────────────
@router.get("/org-units")
async def list_org_units(db: DbSession, _actor: RequireAdmin) -> list[dict]:
    rows = (
        (await db.execute(select(OrgUnit).order_by(OrgUnit.sort_order.asc(), OrgUnit.label.asc())))
        .scalars()
        .all()
    )
    return [_org_dict(o) for o in rows]


@router.post("/org-units", status_code=status.HTTP_201_CREATED)
async def create_org_unit(body: OrgUnitCreate, db: DbSession, _actor: RequireAdmin) -> dict:
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="이름을 입력하세요.")
    max_order = (await db.execute(select(func.max(OrgUnit.sort_order)))).scalar()
    org = OrgUnit(id=f"ou-{uuid.uuid4().hex[:10]}", label=label, sort_order=(max_order or 0) + 1)
    db.add(org)
    await db.commit()
    return _org_dict(org)


@router.patch("/org-units/{org_id}")
async def update_org_unit(
    org_id: str, body: OrgUnitUpdate, db: DbSession, _actor: RequireAdmin
) -> dict:
    org = await db.get(OrgUnit, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="조직구분을 찾을 수 없습니다.")
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="이름을 입력하세요.")
    org.label = label
    await db.commit()
    return _org_dict(org)


@router.delete("/org-units/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org_unit(org_id: str, db: DbSession, _actor: RequireAdmin) -> Response:
    org = await db.get(OrgUnit, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="조직구분을 찾을 수 없습니다.")
    await db.delete(org)  # agent_org_access 는 FK ondelete CASCADE 로 함께 제거.
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/org-units/reorder")
async def reorder_org_units(body: ReorderIn, db: DbSession, _actor: RequireAdmin) -> list[dict]:
    # 부분/stale orderedIds 여도 전체 순열을 재구성해 중복·간극 없는 sort_order 를 보장(리뷰 #3).
    rows = (
        (await db.execute(select(OrgUnit).order_by(OrgUnit.sort_order.asc()))).scalars().all()
    )
    by_id = {o.id: o for o in rows}
    ordered: list[str] = []
    for oid in body.orderedIds:  # 클라가 준 순서 중 실재하는 것만, 중복 제거.
        if oid in by_id and oid not in ordered:
            ordered.append(oid)
    for o in rows:  # 목록에 빠진 나머지는 현재 순서대로 뒤에 붙인다.
        if o.id not in ordered:
            ordered.append(o.id)
    for index, oid in enumerate(ordered):
        by_id[oid].sort_order = index
    await db.commit()
    return await list_org_units(db, _actor)


# ── 에이전트 접근 관리 ─────────────────────────────────────────────────────────
@router.get("/agent-access")
async def list_agent_access(db: DbSession, _actor: RequireAdmin) -> list[dict]:
    """실 에이전트(백엔드 agents 테이블 = card-chat 등)별 사용 가능 조직구분.

    access_configured=false 면 '최초 모두 선택'으로 전체 조직구분 id 를 반환한다.
    """
    all_org_ids = list(
        (
            await db.execute(select(OrgUnit.id).order_by(OrgUnit.sort_order.asc()))
        ).scalars()
    )
    agents = (
        (await db.execute(select(Agent).order_by(Agent.created_at.asc()))).scalars().all()
    )
    access_rows = (await db.execute(select(AgentOrgAccess))).scalars().all()
    by_agent: dict[str, list[str]] = {}
    for r in access_rows:
        by_agent.setdefault(r.agent_id, []).append(r.org_unit_id)
    out: list[dict] = []
    for a in agents:
        if a.access_configured:
            allowed = [oid for oid in all_org_ids if oid in set(by_agent.get(a.id, []))]
        else:
            allowed = list(all_org_ids)  # 최초 = 모두 선택.
        out.append({"agentId": a.id, "agentName": a.name, "orgUnitIds": allowed})
    return out


@router.patch("/agent-access/{agent_id}")
async def set_agent_access(
    agent_id: str, body: AgentAccessSetIn, db: DbSession, _actor: RequireAdmin
) -> dict:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다.")
    valid_ids = set((await db.execute(select(OrgUnit.id))).scalars())
    requested = [oid for oid in dict.fromkeys(body.orgUnitIds) if oid in valid_ids]
    # 비어있지 않은 요청인데 전부 무효 = 클라 목록이 오래됨 → 조용히 전체 해제하지 말고 거부(리뷰 #4).
    if body.orgUnitIds and not requested:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="요청한 조직구분이 모두 유효하지 않습니다. 목록을 새로고침해 주세요.",
        )
    await db.execute(delete(AgentOrgAccess).where(AgentOrgAccess.agent_id == agent_id))
    for oid in requested:
        db.add(AgentOrgAccess(agent_id=agent_id, org_unit_id=oid))
    agent.access_configured = True
    await db.commit()
    # 정의 순서대로 정렬해 반환.
    ordered = list(
        (
            await db.execute(
                select(OrgUnit.id)
                .where(OrgUnit.id.in_(requested))
                .order_by(OrgUnit.sort_order.asc())
            )
        ).scalars()
    )
    return {"agentId": agent_id, "orgUnitIds": ordered}
