"""ERP 조직도(본부▸팀) → org_units 멱등 반영 + 사용자 소속(org_unit_id) 재배치.

code_sync._sync_org 가 erp_code_catalog(미리보기)를 upsert 한 뒤, 실제 권한 단위인
org_units 로도 반영한다. ERP 에는 안정 코드가 없어 **라벨 정규화 매칭**으로 기존 행과 잇고,
신규만 결정적 id(`erp-<sha1>`)로 만든다(재임포트 시 같은 키→같은 행). 기존 행의 id·cost_type 은
절대 바꾸지 않는다 — 사용자/에이전트 링크와 카드 자동화 (판)/(제) 접두 규칙을 보존해야 한다.
ERP 트리에 없는 로컬 조직은 삭제하지 않고(라벨만 수집해 보고) 관리자가 판단하게 둔다.
"""

from __future__ import annotations

import hashlib
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgUnit, User

logger = logging.getLogger(__name__)

# 라벨/부서 매칭 정규화 — 공백·구분기호·괄호 제거 후 소문자. '인사/기획팀'=='인사기획팀',
# '경영 본부'=='경영본부'. catalog._acct_norm 과 같은 문자 집합(‘/’ 포함).
_NORM_STRIP_RE = re.compile(r"[\s()\[\]{}·・,./\\_\-]+")


def _norm(s: object) -> str:
    """조직 라벨/부서명 정규화 — 매칭용 키."""
    return _NORM_STRIP_RE.sub("", str(s or "")).lower()


def _erp_id(key: str) -> str:
    """정규화 키로부터 결정적·안정 OrgUnit id. 재임포트해도 같은 키면 같은 id 라 매칭된다."""
    return f"erp-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def _reuse_row(row: OrgUnit, label: str, order: int) -> bool:
    """기존 org_unit 행 재사용 — sort_order·라벨만 갱신(id·cost_type 불변). 변경됐으면 True."""
    changed = False
    if row.sort_order != order:
        row.sort_order = order
        changed = True
    if row.label != label:  # 라벨이 실제로 다를 때만 갱신(ERP 표기로 정정).
        row.label = label
        changed = True
    return changed


async def apply_org_tree(session: AsyncSession, flat: list[dict]) -> dict:
    """flat(본부▸팀 행) → org_units 멱등 upsert. 반환은 요약 dict.

    매칭 규칙: 본부는 parent_id IS NULL 행 중 정규화 라벨로, 팀은 그 본부 자식 중 (정규화 본부명,
    정규화 팀명)으로 잇는다. 매칭되면 그 행을 재사용(sort_order·라벨만 갱신, id·cost_type 불변),
    없으면 신규 생성(id=erp-<sha1>, cost_type=None). flat 등장 순서로 sort_order 를 부여한다.
    ERP 에 없는 로컬 행은 삭제하지 않고 local_only 로 라벨만 모은다. commit 은 호출자가 한다.
    """
    existing = (await session.execute(select(OrgUnit))).scalars().all()
    hq_by_norm: dict[str, OrgUnit] = {}
    teams_by_parent: dict[str, dict[str, OrgUnit]] = {}
    for o in existing:
        if o.parent_id is None:
            hq_by_norm.setdefault(_norm(o.label), o)
        else:
            teams_by_parent.setdefault(o.parent_id, {}).setdefault(_norm(o.label), o)

    # flat(팀 단위 행)을 (본부 등장순 · 본부별 팀 등장순)으로 접는다 — sort_order 근거.
    hq_seq: list[str] = []  # 정규화 본부명(첫 등장 순)
    hq_label: dict[str, str] = {}  # 정규화 본부명 → 표시 라벨(첫 등장)
    team_seq: dict[str, list[str]] = {}  # 정규화 본부명 → [정규화 팀명 순서]
    team_label: dict[str, dict[str, str]] = {}  # 정규화 본부명 → {정규화 팀명 → 라벨}
    for r in flat:
        nh = _norm(r["hq"])
        if nh not in hq_label:
            hq_label[nh] = r["hq"]
            hq_seq.append(nh)
            team_seq[nh] = []
            team_label[nh] = {}
        nt = _norm(r["team"])
        if nt not in team_label[nh]:
            team_label[nh][nt] = r["team"]
            team_seq[nh].append(nt)

    added: list[str] = []
    updated: list[str] = []
    unchanged = 0
    seen_ids: set[str] = set()

    for hq_order, nh in enumerate(hq_seq):
        label = hq_label[nh]
        hq_match = hq_by_norm.get(nh)
        if hq_match is not None:
            hq_id = hq_match.id
            if _reuse_row(hq_match, label, hq_order):
                updated.append(label)
            else:
                unchanged += 1
            seen_ids.add(hq_id)
        else:
            hq_id = _erp_id(nh)
            session.add(
                OrgUnit(id=hq_id, label=label, parent_id=None, cost_type=None, sort_order=hq_order)
            )
            added.append(label)
            seen_ids.add(hq_id)

        children = teams_by_parent.get(hq_id, {})
        for t_order, nt in enumerate(team_seq[nh]):
            t_label = team_label[nh][nt]
            t_match = children.get(nt)
            if t_match is not None:
                if _reuse_row(t_match, t_label, t_order):
                    updated.append(t_label)
                else:
                    unchanged += 1
                seen_ids.add(t_match.id)
            else:
                team_id = _erp_id(f"{nh}|{nt}")
                session.add(
                    OrgUnit(
                        id=team_id, label=t_label, parent_id=hq_id, cost_type=None, sort_order=t_order
                    )
                )
                added.append(t_label)
                seen_ids.add(team_id)

    local_only = [o.label for o in existing if o.id not in seen_ids]

    await session.flush()
    return {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "local_only": local_only,
        "total_erp": len(flat),
    }


async def match_org_unit_for_department(session: AsyncSession, department: object) -> OrgUnit | None:
    """부서명(ERP)을 org_units 라벨에 정규화 매칭 — 팀(parent 있음) 우선, 없으면 본부. 없으면 None.

    가입·로그인 시 사용자 소속(org_unit_id)을 부서(=조직구분)로 자동 배정하는 단건 조회.
    부서와 조직구분은 같은 개념이라, 부서 문자열이 조직구분 라벨과 정규화 일치하면 그 조직으로 잇는다.
    """
    n = _norm(department)
    if not n:
        return None
    org_units = (await session.execute(select(OrgUnit))).scalars().all()
    team: OrgUnit | None = None
    fallback: OrgUnit | None = None
    for o in org_units:
        if _norm(o.label) != n:
            continue
        if o.parent_id is not None and team is None:
            team = o
        if fallback is None:
            fallback = o
    return team or fallback


async def reconcile_users(session: AsyncSession) -> list[dict]:
    """department 있는 사용자를 org_unit 라벨에 정규화 매칭해 org_unit_id 재배치. 반환은 변경 목록.

    매칭은 팀(parent_id IS NOT NULL) 우선, 없으면 본부(any) 폴백. 매칭돼 소속이 달라질 때만
    갱신한다. 매칭 안 되는 사용자는 그대로 둔다. commit 은 호출자가 한다.
    """
    org_units = (
        (await session.execute(select(OrgUnit).order_by(OrgUnit.sort_order.asc(), OrgUnit.id.asc())))
        .scalars()
        .all()
    )
    team_by_norm: dict[str, OrgUnit] = {}
    any_by_norm: dict[str, OrgUnit] = {}
    for o in org_units:
        n = _norm(o.label)
        any_by_norm.setdefault(n, o)
        if o.parent_id is not None:
            team_by_norm.setdefault(n, o)

    users = (
        (await session.execute(select(User).where(User.department.is_not(None)))).scalars().all()
    )
    changes: list[dict] = []
    for u in users:
        n = _norm(u.department)
        if not n:
            continue
        target = team_by_norm.get(n) or any_by_norm.get(n)
        if target is None:
            continue
        if u.org_unit_id != target.id:
            old = u.org_unit_id
            u.org_unit_id = target.id
            changes.append(
                {
                    "userid": u.omnisol_userid,
                    "from": old,
                    "to": target.id,
                    "department": u.department,
                    "org_label": target.label,
                }
            )
    await session.flush()
    return changes
