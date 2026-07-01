"""멱등 시드 — permissions → roles → role_permissions + 에이전트 목업 (ax 패턴 이식).

여러 번 실행해도 안전:
- 누락된 permission 삽입, 기존은 description 동기화.
- 누락된 role 삽입, 기존은 name/description 동기화 + DEFAULT_ROLES 권한 보강.
  (DEFAULT_ROLES 에 없는 수동 부여 권한은 보존.)
- 에이전트는 id 존재 시 건너뜀(이미 시드됨).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLES, ROLE_SUPER_ADMIN
from app.core.security import hash_password
from app.models import (
    Agent,
    AgentIntervention,
    AgentLog,
    AgentStep,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.agent_fixtures import AGENT_FIXTURES

# 로컬 시스템 관리자 계정(옴니솔 미사용, bcrypt 로컬 검증).
_LOCAL_ADMIN_USERID = "admin"
# ⚠️ '1111' 은 사용자 명시 요청에 의한 약한 부트스트랩 비밀번호다.
#    프로덕션 배포 전 반드시 변경할 것. seed 는 기존 해시를 절대 덮어쓰지 않으므로
#    운영에서 비밀번호를 바꿔도 재시작 시 초기화되지 않는다.
_LOCAL_ADMIN_PASSWORD = "1111"


async def seed_permissions(db: AsyncSession) -> dict[str, Permission]:
    existing = {p.code: p for p in (await db.execute(select(Permission))).scalars()}
    for code, description in ALL_PERMISSIONS.items():
        perm = existing.get(code)
        if perm is None:
            perm = Permission(code=code, description=description)
            db.add(perm)
            existing[code] = perm
        elif perm.description != description:
            perm.description = description
    await db.flush()
    return existing


async def seed_roles(db: AsyncSession, permissions: dict[str, Permission]) -> None:
    stmt = select(Role)
    existing = {r.code: r for r in (await db.execute(stmt)).scalars()}

    for code, (name, description, perm_codes) in DEFAULT_ROLES.items():
        desired = set(perm_codes)
        role = existing.get(code)
        if role is None:
            role = Role(code=code, name=name, description=description)
            db.add(role)
            await db.flush()
            current: set[str] = set()
        else:
            if role.name != name:
                role.name = name
            if role.description != description:
                role.description = description
            current = {rp.permission.code for rp in role.role_permissions}

        for missing in desired - current:
            db.add(RolePermission(role_id=role.id, permission_id=permissions[missing].id))

    await db.flush()


async def seed_agents(db: AsyncSession) -> None:
    existing_ids = set((await db.execute(select(Agent.id))).scalars())
    for fx in AGENT_FIXTURES:
        if fx["id"] in existing_ids:
            continue
        agent = Agent(
            id=fx["id"],
            name=fx["name"],
            description=fx["description"],
            drive=fx["drive"],
            interaction=fx["interaction"],
            target_system=fx["target_system"],
            target_url=fx["target_url"],
            status=fx["status"],
            progress=fx["progress"],
            timeout_seconds=fx["timeout_seconds"],
            elapsed_seconds=fx["elapsed_seconds"],
            current_action=fx["current_action"],
            run_count=fx["run_count"],
            success_rate=fx["success_rate"],
            avg_seconds=fx["avg_seconds"],
            last_run_at=fx["last_run_at"],
            flow_graph=fx["flow_graph"],
        )
        db.add(agent)
        for pos, step in enumerate(fx["steps"]):
            db.add(
                AgentStep(
                    agent_id=agent.id,
                    key=step["key"],
                    label=step["label"],
                    skill=step.get("skill"),
                    status=step["status"],
                    detail=step.get("detail"),
                    position=pos,
                    substeps=step.get("substeps"),
                )
            )
        for pos, log in enumerate(fx["logs"]):
            db.add(
                AgentLog(
                    agent_id=agent.id,
                    key=log["key"],
                    level=log["level"],
                    message=log["message"],
                    step_label=log.get("step"),
                    logged_at=_parse_iso(log.get("at")),
                    position=pos,
                )
            )
        iv = fx.get("intervention")
        if iv is not None:
            db.add(
                AgentIntervention(
                    agent_id=agent.id,
                    kind=iv["kind"],
                    title=iv["title"],
                    prompt=iv["prompt"],
                    options=iv.get("options"),
                    messages=iv.get("messages"),
                    placeholder=iv.get("placeholder"),
                )
            )
    await db.flush()


def _parse_iso(value: str | None):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)


async def seed_local_admin(db: AsyncSession) -> None:
    """로컬 시스템 관리자(admin/1111) 멱등 생성. 옴니솔/헤드리스 미사용.

    이미 존재하면 기존 password_hash 를 덮어쓰지 않는다(운영 비밀번호 변경 보존).
    누락된 password_hash·role 만 보강한다.
    """
    admin = (
        await db.execute(select(User).where(User.omnisol_userid == _LOCAL_ADMIN_USERID))
    ).scalar_one_or_none()
    role = (
        await db.execute(select(Role).where(Role.code == ROLE_SUPER_ADMIN))
    ).scalar_one_or_none()

    if admin is None:
        db.add(
            User(
                omnisol_userid=_LOCAL_ADMIN_USERID,
                display_name="시스템 관리자",
                password_hash=hash_password(_LOCAL_ADMIN_PASSWORD),
                role_id=role.id if role is not None else None,
                status="active",
            )
        )
        await db.flush()
        return

    changed = False
    if admin.password_hash is None:
        admin.password_hash = hash_password(_LOCAL_ADMIN_PASSWORD)
        changed = True
    if admin.role_id is None and role is not None:
        admin.role_id = role.id
        changed = True
    if changed:
        await db.flush()


async def seed_all(db: AsyncSession) -> None:
    """전체 시드를 1개 트랜잭션 흐름으로 실행. 호출자가 commit 한다."""
    permissions = await seed_permissions(db)
    await seed_roles(db, permissions)
    await seed_local_admin(db)
    await seed_agents(db)
