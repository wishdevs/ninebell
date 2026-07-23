"""멱등 시드 — permissions → roles → role_permissions + 에이전트 목업 (ax 패턴 이식).

여러 번 실행해도 안전:
- 누락된 permission 삽입, 기존은 description 동기화.
- 누락된 role 삽입, 기존은 name/description 동기화 + DEFAULT_ROLES 권한 보강.
  (DEFAULT_ROLES 에 없는 수동 부여 권한은 보존.)
- 에이전트는 id 존재 시 건너뜀(이미 시드됨).
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

from sqlalchemy import delete, select
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
    CardSeedNote,
    CardSeedSelection,
    OrgUnit,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.agent_fixtures import AGENT_FIXTURES, AGENT_GROUP_FIXTURES
from app.services.card_learning import sanitize_note
from app.services.org_apply import _erp_id, _existing_path, _norm

# 조직구분 시드 — ERP 조직도를 **전체 깊이**로 미러링한 기본 구조(본부>그룹>팀). org_apply 임포트와
# **같은 경로해시 id**(_erp_id(정규화 경로))로 심어, 'ERP 조직도 불러오기'가 돌면 그대로 매칭돼
# 중복/드리프트가 없다(옛 2단계 slug 시드를 대체 — 재시작/재배포마다 실제 ERP 구조 유지).
# 마이그레이션 0011(2단계 slug)은 레거시로, 라이브 임포트가 prune 해 정리한다.
# (path=[상위라벨...,self], 비용구분, 인원수). 인원수=서브트리 합계(직속 인원 판별용). 순수
# 컨테이너(직속 0, 예: 경영본부 31 = 자식합)는 cost_type=None. 직속 인원을 가진 노드(말단 팀,
# 그리고 재무자원관리그룹 11≠자식합 10 처럼 직속 1 인 중간 그룹)는 판/제 비용구분을 가질 수 있다.
_SGA = "판관비"
_MFG = "제조원가"
_ORG_TREE_SEED: tuple[tuple[tuple[str, ...], str | None, int], ...] = (
    (("임원실",), None, 6),
    (("임원실", "비서실"), _MFG, 1),
    (("경영본부",), None, 31),
    (("경영본부", "재무자원관리그룹"), None, 11),
    (("경영본부", "재무자원관리그룹", "자재팀"), _MFG, 3),
    (("경영본부", "재무자원관리그룹", "회계팀"), _SGA, 4),
    (("경영본부", "재무자원관리그룹", "총무팀"), _SGA, 3),
    (("경영본부", "구매팀"), _MFG, 6),
    (("경영본부", "인사/기획팀"), _SGA, 4),
    (("경영본부", "품질팀"), _MFG, 10),
    (("영업본부",), None, 10),
    (("영업본부", "영업본부장"), _SGA, 1),
    (("영업본부", "영업팀"), _SGA, 5),
    (("영업본부", "CS팀"), _SGA, 1),
    (("영업본부", "영업관리팀"), _SGA, 3),
    (("중국법인",), _MFG, 12),
    (("FA연구소",), None, 44),
    (("FA연구소", "FA본부장"), _MFG, 1),
    (("FA연구소", "설계1팀"), _MFG, 7),
    (("FA연구소", "전장팀"), _MFG, 6),
    (("FA연구소", "설계2팀"), _MFG, 7),
    (("FA연구소", "설계3팀"), _MFG, 5),
    (("FA연구소", "제어1팀"), _MFG, 6),
    (("FA연구소", "제어2팀"), _MFG, 8),
    (("FA연구소", "연구기획팀"), _MFG, 2),
    (("FA연구소", "고문"), _MFG, 2),
    (("제조본부",), None, 43),
    (("제조본부", "제조1팀"), _MFG, 25),
    (("제조본부", "제조2팀"), _MFG, 17),
    (("제조본부", "고문"), _MFG, 1),
    (("IMP연구소",), None, 13),
    (("IMP연구소", "IMP1팀"), _SGA, 4),
    (("IMP연구소", "IMP2팀"), _SGA, 5),
    (("IMP연구소", "IMP3팀"), _SGA, 2),
    (("IMP연구소", "IMP본부장"), _MFG, 1),
    (("더존컨설팅",), _MFG, 9),
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
    # 픽스처에서 제거된 그룹은 DB 에서도 정리(자재팀 제거 2026-07-21 — 픽스처가 단일 소스).
    # 소속 에이전트의 group_id 는 FK ondelete=SET NULL 로 끊기고, 에이전트 자체는 seed_agents 가 prune.
    fixture_gids = {fx["id"] for fx in AGENT_GROUP_FIXTURES}
    for gid, group in existing.items():
        if gid not in fixture_gids:
            await db.delete(group)
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
            # 실행 표시 필드(flow_graph·interaction·drive) 동기화 — 픽스처가 단일 소스. 더미를 실동작
            # 으로 승격할 때 이 필드들이 낡은 더미값으로 잔존하는 것을 막는다(trip-domestic 승격 실측
            # 2026-07-06: workflow_id·steps 는 승격됐으나 interaction='conversational'·flow_graph 가
            # 더미로 남아 워크플로우 탭이 잘못 표시됐다).
            if row.flow_graph != fx["flow_graph"]:
                row.flow_graph = fx["flow_graph"]
            if row.interaction != fx["interaction"]:
                row.interaction = fx["interaction"]
            if row.drive != fx["drive"]:
                row.drive = fx["drive"]
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
    # 픽스처에서 제거된 에이전트는 DB 에서도 정리(자재팀 더미·구 데모 등 — 픽스처가 단일 소스).
    # steps/logs/interventions 는 Agent 관계 cascade(all, delete-orphan)로 함께 삭제된다.
    fixture_ids = {fx["id"] for fx in AGENT_FIXTURES}
    for aid, row in existing.items():
        if aid not in fixture_ids:
            await db.delete(row)
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
    """조직구분 시드 — ERP 전체 깊이 기본 구조를 멱등 삽입(경로해시 id, 이미 있으면 건너뜀).

    id/부모 연결은 org_apply.apply_org_tree 와 동일 규칙(_erp_id(정규화 경로)) — 'ERP 조직도
    불러오기'가 돌면 같은 id 로 매칭돼 중복이 없다. 여기선 prune 하지 않는다(기본 존재만 보장).
    """
    existing = (await db.execute(select(OrgUnit))).scalars().all()
    by_id = {o.id: o for o in existing}
    # 기존 행을 **정규화 경로**로 인덱싱 — id 가 무엇이든(옛 slug·임포트 재사용 id) 경로가 같으면
    # 같은 노드로 보고 재사용한다(중복 생성 방지). apply_org_tree 와 동일한 경로 개념.
    existing_id_by_path: dict[tuple[str, ...], str] = {}
    for o in existing:
        existing_id_by_path.setdefault(_existing_path(o, by_id), o.id)

    id_by_path: dict[tuple[str, ...], str] = {}
    for order, (path, cost, count) in enumerate(_ORG_TREE_SEED):
        npath = tuple(_norm(lbl) for lbl in path)
        parent_id = id_by_path.get(npath[:-1]) if len(npath) > 1 else None
        existing_id = existing_id_by_path.get(npath)
        if existing_id is not None:
            node_id = existing_id  # 이미 존재(경로 기준) — id 재사용, 중복 생성 안 함.
            # 인원수만 백필한다(None 인 기존 행에만). cost_type 은 운영자 설정을 덮지 않도록 건드리지 않음.
            row = by_id.get(node_id)
            if row is not None and row.member_count is None:
                row.member_count = count
        else:
            node_id = _erp_id("|".join(npath))
            db.add(
                OrgUnit(
                    id=node_id,
                    label=path[-1],
                    parent_id=parent_id,
                    cost_type=cost,
                    member_count=count,
                    sort_order=order,
                )
            )
        id_by_path[npath] = node_id
    await db.flush()


# 전사 카드 기초자료 시드 파일(레포 커밋) — app/data/card_seed_selections.json.gz.
_CARD_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "card_seed_selections.json.gz"
# (가맹점 × 계정) → 적요 시드 파일(레포 커밋) — app/data/card_seed_notes.json.gz.
_CARD_SEED_NOTES_PATH = Path(__file__).resolve().parent.parent / "data" / "card_seed_notes.json.gz"


async def seed_card_seeds(db: AsyncSession, force: bool = False) -> None:
    """전사 카드 기초자료(card_seed_selections) 멱등 시드 — 비어있을 때만 gz 파일에서 적재.

    가맹점→계정·적요 집계(레포 커밋 시드). 누적/갱신분(사용·재임포트) 보존을 위해 테이블이
    비어있을 때만 넣는다. 파일이 없으면 경고만 남기고 건너뛴다(스타트업 실패 방지).

    `force=True`면 커밋된 gz 를 진실로 보고 **기존 행을 비우고 다시 적재**한다(커밋 시드를
    수정한 뒤 반영할 때 — `scripts/reseed_card_seed.py`. card_seed_selections 은 런타임 누적이
    없어 교체가 안전하다). 스타트업 자동 시드는 force 를 쓰지 않는다.
    """
    if not force and (await db.execute(select(CardSeedSelection.id).limit(1))).first() is not None:
        return  # 이미 데이터 존재(시드됨 또는 누적) — 건너뜀.
    if not _CARD_SEED_PATH.exists():
        logger.warning("card_seed 파일 없음(%s) — 카드 기초자료 시드 건너뜀.", _CARD_SEED_PATH)
        return
    if force:
        await db.execute(delete(CardSeedSelection))  # 커밋 gz 로 전량 교체(재적재).
    with gzip.open(_CARD_SEED_PATH, "rb") as fh:
        rows = json.loads(fh.read().decode("utf-8"))
    for r in rows:
        db.add(
            CardSeedSelection(
                norm_merchant=r["norm_merchant"],
                merchant=r["merchant"],
                acct_code=r.get("acct_code"),
                acct_name=r.get("acct_name"),
                note=r.get("note"),
                count=r.get("count", 1),
                dominance=r.get("dominance", 1.0),
                last_year=r.get("last_year"),
            )
        )
    await db.flush()
    logger.info("card_seed 시드: %d행 적재(%s).", len(rows), _CARD_SEED_PATH.name)


async def seed_card_seed_notes(db: AsyncSession, force: bool = False) -> None:
    """전사 (가맹점 × 계정) → 적요(card_seed_notes) 멱등 시드 — 비어있을 때만 gz 파일에서 적재.

    seed_card_seeds 미러. 누적/갱신분(사용·재임포트) 보존을 위해 테이블이 비어있을 때만 넣는다.
    파일이 없으면 경고만 남기고 건너뛴다(스타트업 실패 방지).

    `force=True`면 gz 로 전량 교체한다(reseed). ⚠ card_seed_notes 는 `card_seed_remap`
    (ERP 카탈로그 9자리 재키잉)이 런타임에 갱신하므로, force 재적재 후엔 필요 시 remap 을 다시
    돌려야 한다. 스타트업 자동 시드는 force 를 쓰지 않는다.
    """
    if not force and (await db.execute(select(CardSeedNote.id).limit(1))).first() is not None:
        return  # 이미 데이터 존재(시드됨 또는 누적) — 건너뜀.
    if not _CARD_SEED_NOTES_PATH.exists():
        logger.warning(
            "card_seed_notes 파일 없음(%s) — 계정별 적요 시드 건너뜀.", _CARD_SEED_NOTES_PATH
        )
        return
    if force:
        await db.execute(delete(CardSeedNote))  # gz 로 전량 교체(재적재).
    with gzip.open(_CARD_SEED_NOTES_PATH, "rb") as fh:
        rows = json.loads(fh.read().decode("utf-8"))
    for r in rows:
        db.add(
            CardSeedNote(
                norm_merchant=r["norm_merchant"],
                merchant=r["merchant"],
                acct_code=r["acct_code"],
                acct_name=r.get("acct_name"),
                # 기록 경로 정리 — 시드 gz 에 남은 PII(차량번호·이름 괄호)가 재적재로 재오염되지 않게.
                note=sanitize_note(r.get("note")),
                count=r.get("count", 1),
                dominance=r.get("dominance", 1.0),
                last_year=r.get("last_year"),
            )
        )
    await db.flush()
    logger.info("card_seed_notes 시드: %d행 적재(%s).", len(rows), _CARD_SEED_NOTES_PATH.name)


async def seed_all(db: AsyncSession) -> None:
    """전체 시드를 1개 트랜잭션 흐름으로 실행. 호출자가 commit 한다."""
    permissions = await seed_permissions(db)
    await seed_roles(db, permissions)
    await seed_local_admin(db)
    await seed_agent_groups(db)  # FK: seed_agents 의 group_id 보다 먼저.
    await seed_agents(db)
    await seed_org_units(db)
    await seed_card_seeds(db)
    await seed_card_seed_notes(db)
