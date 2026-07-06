"""멱등 시드 — permissions → roles → role_permissions + 에이전트 목업 (ax 패턴 이식).

여러 번 실행해도 안전:
- 누락된 permission 삽입, 기존은 description 동기화.
- 누락된 role 삽입, 기존은 name/description 동기화 + DEFAULT_ROLES 권한 보강.
  (DEFAULT_ROLES 에 없는 수동 부여 권한은 보존.)
- 에이전트는 id 존재 시 건너뜀(이미 시드됨).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLES, ROLE_SUPER_ADMIN
from app.core.security import hash_password, verify_password

logger = logging.getLogger("app.services.seed")
from app.models import (
    Agent,
    AgentGroup,
    AgentIntervention,
    AgentLog,
    AgentStep,
    OrgUnit,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.agent_fixtures import AGENT_FIXTURES, AGENT_GROUP_FIXTURES

# 조직구분 기준 데이터 — alembic 0005 와 동일. create_all 부트스트랩/SQLite 테스트 경로에서도
# 동일하게 존재하도록 여기서도 멱등 시드한다(리뷰 #5·#12: 마이그레이션에만 있으면 경로 불일치).
# 조직구분 2뎁스 시드 — 마이그레이션 0011 과 동일한 slug/구조를 유지한다(런타임=마이그레이션).
# (본부 slug, 본부 라벨, [(팀 라벨, 비용구분), ...]). 팀 id = f"{본부slug}__t{index}".
_SGA = "판관비"
_MFG = "제조원가"
_ORG_HIERARCHY: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("hq_sales_head", "영업본부장", (("영업본부장", _SGA),)),
    ("hq_sales", "영업본부", (("영업팀", _SGA), ("영업관리팀", _SGA), ("CS팀", _SGA))),
    ("hq_mgmt", "경영본부", (
        ("인사기획팀", _SGA), ("총무팀", _SGA), ("회계팀", _SGA),
        ("구매팀", _MFG), ("자재팀", _MFG), ("품질팀", _MFG),
    )),
    ("hq_imp_head", "IMP연구소 본부장", (("IMP연구소 본부장", _SGA),)),
    ("hq_imp_group", "IMP연구소 그룹장", (("IMP연구소 그룹장", _SGA),)),
    ("hq_imp", "IMP연구소", (("IMP1팀", _SGA), ("IMP2팀", _SGA), ("IMP3팀", _SGA))),
    ("hq_fa_head", "FA연구소 본부장", (("FA연구소 본부장", _MFG),)),
    ("hq_fa_advisor", "FA고문", (("FA고문", _MFG),)),
    ("hq_fa", "FA연구소", (("연구기획팀", _MFG),)),
    ("hq_fa_design", "FA연구소 (설계그룹)", (("설계1팀", _MFG), ("설계2팀", _MFG), ("설계3팀", _MFG))),
    ("hq_fa_control", "FA연구소 (제어그룹)", (("전장팀", _MFG), ("제어1팀", _MFG), ("제어2팀", _MFG))),
    ("hq_exec", "임원", (("임원실", _SGA),)),
    ("hq_mfg", "제조본부", (
        ("제조1-A팀", _MFG), ("제조1-B팀", _MFG), ("제조1-전장팀", _MFG),
        ("로봇팀", _MFG), ("제조2팀", _MFG), ("생산관리팀", _MFG),
    )),
    ("hq_mfg_advisor", "제조고문", (("제조고문", _MFG),)),
)

# 로컬 시스템 관리자 계정(옴니솔 미사용, bcrypt 로컬 검증).
_LOCAL_ADMIN_USERID = "admin"
# env LOCAL_ADMIN_PASSWORD 미설정 시 폴백. 프로덕션 금지(seed 가 critical 경고).
_FALLBACK_ADMIN_PASSWORD = "1111"


def _resolve_admin_password() -> str:
    """env(local_admin_password) 우선, 없으면 폴백 '1111' + critical 경고."""
    pw = (get_settings().local_admin_password or "").strip()
    if pw:
        return pw
    logger.critical(
        "LOCAL_ADMIN_PASSWORD 미설정 — 기본 비밀번호 '1111' 사용 중. 프로덕션 배포 금지."
    )
    return _FALLBACK_ADMIN_PASSWORD


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


async def seed_agent_groups(db: AsyncSession) -> None:
    """에이전트 그룹 멱등 upsert — 기존 행도 name/description/sort_order 를 픽스처와 동기화."""
    existing = {g.id: g for g in (await db.execute(select(AgentGroup))).scalars()}
    for fx in AGENT_GROUP_FIXTURES:
        group = existing.get(fx["id"])
        if group is None:
            db.add(
                AgentGroup(
                    id=fx["id"],
                    name=fx["name"],
                    description=fx.get("description"),
                    sort_order=fx.get("sort_order", 0),
                )
            )
            continue
        if group.name != fx["name"]:
            group.name = fx["name"]
        if group.description != fx.get("description"):
            group.description = fx.get("description")
        if group.sort_order != fx.get("sort_order", 0):
            group.sort_order = fx.get("sort_order", 0)
    await db.flush()


async def seed_agents(db: AsyncSession) -> None:
    existing = {a.id: a for a in (await db.execute(select(Agent))).scalars()}
    for fx in AGENT_FIXTURES:
        if fx["id"] in existing:
            # 기존 행 멱등 보강: workflow_id 미설정(0006 이전 시드 등)이면 픽스처 값으로 채운다.
            row = existing[fx["id"]]
            if row.workflow_id is None and fx.get("workflow_id"):
                row.workflow_id = fx["workflow_id"]
            # 에이전트 런타임 표시 필드 동기화 — 픽스처가 유일 소스(런타임에 쓰는 코드 없음).
            # 목업 시절의 가짜 진행 상태(waiting_input·progress 72)가 DB 에 눌어붙는 것 방지
            # (2026-07-05 사용자 지적: 열자마자 '개입 필요·진행 중'으로 보임).
            for f in ("status", "progress", "elapsed_seconds", "current_action"):
                if getattr(row, f) != fx[f]:
                    setattr(row, f, fx[f])
            # 그룹 소속(0016 그룹 도입분) 동기화.
            if row.group_id != fx.get("group_id"):
                row.group_id = fx.get("group_id")
            # 이름·설명 동기화 — 픽스처가 단일 소스(개명: '결의서 입력 - 카드' → '카드' 등).
            if row.name != fx["name"]:
                row.name = fx["name"]
            if row.description != fx["description"]:
                row.description = fx["description"]
            # 완료 후 핸드오프 안내(0017) 동기화 — 신규 컬럼은 기존 DB 행에 자동 반영되지 않으므로
            # 여기서 픽스처 값을 따라가게 한다.
            if row.handoff_note != fx.get("handoff_note"):
                row.handoff_note = fx.get("handoff_note")
            # ⚠ settings(0018)는 시드가 동기화하지 않는다 — 관리자가 저장한 값을 시드가
            #   덮으면 안 된다. 정의(스키마·기본값)는 app/services/agent_settings.py 가 소스.
            # 스텝 멱등 보강: skill(카탈로그 키 전환분)·intervention·phase 를 픽스처와 동기화.
            # ⚠ 픽스처 스텝 정의가 통째로 바뀌면(키 셋 불일치 — 예: 옛 flow_graph 기반
            # access/kind/… → 실행 그래프 기반 login/…) 키 매칭 보강은 no-op 이 되어 낡은
            # 스텝이 영구 잔존한다(2026-07-05 실측: 워크플로우 탭이 옛 플랜(대기) + raw 영어
            # 라이브 스텝으로 이중 표시). 키 셋이 다르면 스텝 전체를 픽스처로 교체한다.
            fixture_steps = {s["key"]: s for s in fx["steps"]}
            if {st.key for st in row.steps} != set(fixture_steps):
                for st in list(row.steps):
                    await db.delete(st)
                for pos, step in enumerate(fx["steps"]):
                    db.add(
                        AgentStep(
                            agent_id=row.id,
                            key=step["key"],
                            label=step["label"],
                            skill=step.get("skill"),
                            status=step["status"],
                            detail=step.get("detail"),
                            intervention=step.get("intervention", False),
                            phase=step.get("phase"),
                            position=pos,
                            substeps=step.get("substeps"),
                        )
                    )
                continue
            for st in row.steps:
                fs = fixture_steps.get(st.key)
                if fs is None:
                    continue
                if st.skill != fs.get("skill"):
                    st.skill = fs.get("skill")
                if st.intervention != fs.get("intervention", False):
                    st.intervention = fs.get("intervention", False)
                # label/detail/status/phase 도 픽스처를 따른다(목업 done/active 잔존 방지 —
                # 계획은 전부 pending, 진행 상태는 라이브 스텝이 담당).
                if st.label != fs["label"]:
                    st.label = fs["label"]
                if st.detail != fs.get("detail"):
                    st.detail = fs.get("detail")
                if st.status != fs["status"]:
                    st.status = fs["status"]
                if st.phase != fs.get("phase"):
                    st.phase = fs.get("phase")
            continue
        agent = Agent(
            id=fx["id"],
            workflow_id=fx.get("workflow_id"),
            group_id=fx.get("group_id"),
            name=fx["name"],
            description=fx["description"],
            handoff_note=fx.get("handoff_note"),
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
                    intervention=step.get("intervention", False),
                    phase=step.get("phase"),
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
    """로컬 시스템 관리자(admin) 멱등 생성/보강. 옴니솔/헤드리스 미사용.

    비밀번호는 env(LOCAL_ADMIN_PASSWORD) 우선. 운영자가 수동 변경한 해시는 절대 덮어쓰지 않되,
    **기존 해시가 폴백 '1111' 과 일치할 때만** env 값으로 회전(기본값 강제 탈피 유도). 누락된
    password_hash·role 도 보강한다.
    """
    password = _resolve_admin_password()
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
                password_hash=hash_password(password),
                role_id=role.id if role is not None else None,
                status="active",
            )
        )
        await db.flush()
        return

    changed = False
    if admin.password_hash is None:
        admin.password_hash = hash_password(password)
        changed = True
    elif (
        password != _FALLBACK_ADMIN_PASSWORD
        and verify_password(_FALLBACK_ADMIN_PASSWORD, admin.password_hash)
    ):
        # 기존이 기본값('1111')이고 env 로 새 비밀번호가 주어졌을 때만 회전(운영 변경분은 불변).
        admin.password_hash = hash_password(password)
        changed = True
        logger.warning("LOCAL_ADMIN_PASSWORD 로 admin 기본 비밀번호를 회전했습니다.")
    if admin.role_id is None and role is not None:
        admin.role_id = role.id
        changed = True
    if changed:
        await db.flush()


async def seed_org_units(db: AsyncSession) -> None:
    """조직구분 2뎁스(본부→팀) 멱등 시드(id 슬러그 기준, 이미 있으면 건너뜀)."""
    existing = set((await db.execute(select(OrgUnit.id))).scalars())
    for hq_i, (hq_slug, hq_label, teams) in enumerate(_ORG_HIERARCHY):
        if hq_slug not in existing:
            db.add(OrgUnit(id=hq_slug, label=hq_label, parent_id=None, cost_type=None, sort_order=hq_i))
        for t_i, (team_label, cost) in enumerate(teams):
            team_id = f"{hq_slug}__t{t_i}"
            if team_id not in existing:
                db.add(OrgUnit(id=team_id, label=team_label, parent_id=hq_slug,
                               cost_type=cost, sort_order=t_i))
    await db.flush()


async def seed_all(db: AsyncSession) -> None:
    """전체 시드를 1개 트랜잭션 흐름으로 실행. 호출자가 commit 한다."""
    permissions = await seed_permissions(db)
    await seed_roles(db, permissions)
    await seed_local_admin(db)
    await seed_agent_groups(db)  # FK: seed_agents 의 group_id 보다 먼저.
    await seed_agents(db)
    await seed_org_units(db)
