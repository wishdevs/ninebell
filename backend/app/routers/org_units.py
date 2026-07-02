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
from app.models.org_unit import COST_TYPES

router = APIRouter(tags=["org-units"])

RequireAdmin = Annotated[User, Depends(require_role_min(role_rank(ROLE_ADMIN)))]

# '미지정'(org_unit_id IS NULL 사용자) 을 orgUnitIds 목록에서 표현하는 wire 센티널.
# 프론트 멤버 화면의 ORG_NONE 과 동일 문자열 — 실 OrgUnit id 와 충돌하지 않는다.
ORG_NONE_SENTINEL = "__none__"


# ── 스키마 ────────────────────────────────────────────────────────────────────
class OrgUnitCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    parentId: str | None = None  # 지정 시 팀(하위), 없으면 본부(상위).
    costType: str | None = None  # 팀에만 의미(판관비/제조원가).


class OrgUnitUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    costType: str | None = None  # 팀 비용구분 변경.


class ReorderIn(BaseModel):
    parentId: str | None = None  # 이 본부의 팀들을 재정렬. None 이면 본부들 재정렬.
    orderedIds: list[str]


class AgentAccessSetIn(BaseModel):
    orgUnitIds: list[str]


def _org_dict(o: OrgUnit) -> dict:
    return {
        "id": o.id,
        "label": o.label,
        "parentId": o.parent_id,
        "costType": o.cost_type,
        "sortOrder": o.sort_order,
    }


def _validate_cost_type(cost: str | None) -> None:
    if cost is not None and cost not in COST_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"비용구분은 {'/'.join(COST_TYPES)} 중 하나여야 합니다.",
        )


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
    _validate_cost_type(body.costType)
    parent_id = body.parentId
    cost_type = None
    if parent_id is not None:
        parent = await db.get(OrgUnit, parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="상위 본부를 찾을 수 없습니다.")
        if parent.parent_id is not None:
            # 2뎁스 고정 — 팀 아래에 다시 하위를 만들 수 없다.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="팀 아래에는 하위 조직을 만들 수 없습니다(본부→팀 2단계).",
            )
        cost_type = body.costType  # 팀에만 비용구분.
    # 형제(같은 parent) 범위 내 최대 sort_order + 1.
    max_order = (
        await db.execute(
            select(func.max(OrgUnit.sort_order)).where(OrgUnit.parent_id.is_(parent_id))
            if parent_id is None
            else select(func.max(OrgUnit.sort_order)).where(OrgUnit.parent_id == parent_id)
        )
    ).scalar()
    org = OrgUnit(
        id=f"ou-{uuid.uuid4().hex[:10]}",
        label=label,
        parent_id=parent_id,
        cost_type=cost_type,
        sort_order=(max_order or 0) + 1,
    )
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
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="이름을 입력하세요.")
        org.label = label
    if body.costType is not None:
        _validate_cost_type(body.costType)
        if org.parent_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="비용구분은 팀에만 지정할 수 있습니다.",
            )
        org.cost_type = body.costType
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
    # parentId 범위(같은 형제)만 재정렬한다. None 이면 본부들, 값이면 그 본부의 팀들.
    # 부분/stale orderedIds 여도 형제 전체 순열을 재구성해 중복·간극 없는 sort_order 를 보장.
    sibling_filter = (
        OrgUnit.parent_id.is_(None) if body.parentId is None else OrgUnit.parent_id == body.parentId
    )
    rows = (
        (
            await db.execute(
                select(OrgUnit).where(sibling_filter).order_by(OrgUnit.sort_order.asc())
            )
        )
        .scalars()
        .all()
    )
    by_id = {o.id: o for o in rows}
    ordered: list[str] = []
    for oid in body.orderedIds:  # 클라가 준 순서 중 이 형제집합에 실재하는 것만, 중복 제거.
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

    access_configured=false 면 '최초 모두 선택'으로 전체 조직구분 id(+미지정)를 반환한다.
    '미지정'(조직 미배정 사용자 허용)은 ORG_NONE_SENTINEL 로 orgUnitIds 끝에 표현한다.
    """
    # 접근 배정은 팀(leaf, parent_id IS NOT NULL)에만. 본부는 그룹핑용이라 제외.
    all_org_ids = list(
        (
            await db.execute(
                select(OrgUnit.id)
                .where(OrgUnit.parent_id.is_not(None))
                .order_by(OrgUnit.sort_order.asc())
            )
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
            if a.allow_unassigned:
                allowed.append(ORG_NONE_SENTINEL)
        else:
            # 최초 = 모두 선택(미지정 포함 — 게이트도 미설정 상태에선 검사하지 않는다).
            allowed = [*all_org_ids, ORG_NONE_SENTINEL]
        out.append({"agentId": a.id, "agentName": a.name, "orgUnitIds": allowed})
    return out


@router.patch("/agent-access/{agent_id}")
async def set_agent_access(
    agent_id: str, body: AgentAccessSetIn, db: DbSession, _actor: RequireAdmin
) -> dict:
    # 동시 PATCH 직렬화 — delete→insert 패턴이라 잠금 없이는 뒤 요청의 DELETE 가 앞 요청의
    # 미커밋 INSERT 를 못 보고 같은 행을 다시 넣어 PK 중복 500 이 난다(빠른 체크박스 토글 재현).
    # SQLite(테스트)에선 FOR UPDATE 가 no-op 이지만 단일 커넥션이라 무해.
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id).with_for_update())
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="에이전트를 찾을 수 없습니다.")
    # 팀(leaf)만 유효한 접근 대상 — 본부 id 로는 접근을 줄 수 없다.
    valid_ids = set(
        (await db.execute(select(OrgUnit.id).where(OrgUnit.parent_id.is_not(None)))).scalars()
    )
    allow_unassigned = ORG_NONE_SENTINEL in body.orgUnitIds
    requested = [oid for oid in dict.fromkeys(body.orgUnitIds) if oid in valid_ids]
    # 비어있지 않은 요청인데 전부 무효(미지정 센티널도 없음) = 클라 목록이 오래됨 → 조용히 전체 해제하지 말고 거부(리뷰 #4).
    if body.orgUnitIds and not requested and not allow_unassigned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="요청한 조직구분이 모두 유효하지 않습니다. 목록을 새로고침해 주세요.",
        )
    await db.execute(delete(AgentOrgAccess).where(AgentOrgAccess.agent_id == agent_id))
    for oid in requested:
        db.add(AgentOrgAccess(agent_id=agent_id, org_unit_id=oid))
    agent.access_configured = True
    agent.allow_unassigned = allow_unassigned
    await db.commit()
    # 정의 순서대로 정렬해 반환(미지정은 끝).
    ordered = list(
        (
            await db.execute(
                select(OrgUnit.id)
                .where(OrgUnit.id.in_(requested))
                .order_by(OrgUnit.sort_order.asc())
            )
        ).scalars()
    )
    if allow_unassigned:
        ordered.append(ORG_NONE_SENTINEL)
    return {"agentId": agent_id, "orgUnitIds": ordered}
