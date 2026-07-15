"""ERP 조직도(전체 깊이) → org_units 멱등 반영 + 사용자 소속(org_unit_id) 재배치.

code_sync._sync_org 가 erp_code_catalog(미리보기)를 upsert 한 뒤, 실제 권한 단위인
org_units 로도 ERP 트리를 **깊이 그대로** 미러링한다(본부>그룹>…>팀 중간 계층 보존).
ERP 에는 안정 코드가 없어 **정규화 라벨 경로**로 기존 행과 잇고(재편돼도 같은 경로→같은 행),
신규만 결정적 id(`erp-<sha1>`)로 만든다. 기존 행의 id 는 보존하고(사용자/에이전트 링크 유지),
cost_type 도 원칙적으로 보존한다 — 다만 말단(leaf) 팀은 카드 자동화 (판)/(제) 규칙상 반드시
비용구분이 있어야 하므로 없으면 제조원가로 보정한다("재편되면 기존의 것을 따라간다").
ERP 트리에 없는 로컬 조직은 삭제한다(미러링 — 사용자는 org_unit_id=NULL, 에이전트 접근은 제거).
"""

from __future__ import annotations

import hashlib
import logging
import re

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgUnit, User
from app.models.org_unit import COST_TYPE_MFG, AgentOrgAccess

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


def _existing_path(row: OrgUnit, by_id: dict[str, OrgUnit]) -> tuple[str, ...]:
    """기존 org_unit 의 정규화 라벨 경로(root→self) 를 parent_id 로 거슬러 복원. 순환은 방어."""
    labels: list[str] = []
    cur: OrgUnit | None = row
    walked: set[str] = set()
    while cur is not None and cur.id not in walked:
        walked.add(cur.id)
        labels.append(_norm(cur.label))
        cur = by_id.get(cur.parent_id) if cur.parent_id else None
    return tuple(reversed(labels))


def _apply_match(match: OrgUnit, label: str, parent_id: str | None, order: int, is_leaf: bool) -> bool:
    """매칭된 기존 행에 라벨·부모·정렬을 반영. cost_type 은 보존(단, leaf+None 이면 제조원가 보정).

    id 는 절대 바꾸지 않는다(사용자/에이전트 링크 유지). 실제로 무언가 바뀌면 True.
    """
    changed = False
    if match.label != label:  # ERP 표기로 라벨 정정.
        match.label = label
        changed = True
    if match.parent_id != parent_id:  # 재편(부모 이동) 반영.
        match.parent_id = parent_id
        changed = True
    if match.sort_order != order:
        match.sort_order = order
        changed = True
    if is_leaf and match.cost_type is None:  # 말단 팀은 비용구분 필수 — 없으면 제조원가.
        match.cost_type = COST_TYPE_MFG
        changed = True
    return changed


async def apply_org_tree(session: AsyncSession, nodes: list[dict]) -> dict:
    """nodes(전체 깊이·전위순회) → org_units 멱등 미러링. 반환은 요약 dict.

    nodes = org_sync.build_full_tree 반환 [{path:[상위라벨...,self], label, count, is_leaf}].
    매칭: 정규화 라벨 경로(root→self)로 기존 행과 잇는다. 매칭되면 재사용(id 불변, 라벨·부모·정렬
    갱신, cost_type 보존·leaf 보정), 없으면 신규(id=erp-<sha1(경로)>). 전위순회 index 로 sort_order.
    ERP 에 없는 로컬 행은 prune 한다 — 사용자 org_unit_id=NULL·에이전트 접근 삭제 후 행 삭제.
    commit 은 호출자가 한다.
    """
    existing = (await session.execute(select(OrgUnit))).scalars().all()
    by_id = {o.id: o for o in existing}

    # 기존 행 → 정규화 라벨 경로 매칭 인덱스. 동일 경로 중복은 첫 행이 이긴다(방어).
    existing_by_path: dict[tuple[str, ...], OrgUnit] = {}
    for o in existing:
        existing_by_path.setdefault(_existing_path(o, by_id), o)

    # cost_type 상속 — 라벨 정규화 → 기존 cost_type(첫 등장). 재편/개명된 팀이 기존 비용구분을 따라간다.
    costtype_by_label: dict[str, str] = {}
    for o in existing:
        if o.cost_type:
            costtype_by_label.setdefault(_norm(o.label), o.cost_type)

    added: list[str] = []
    updated = 0
    unchanged = 0
    id_by_path: dict[tuple[str, ...], str] = {}
    seen_ids: set[str] = set()

    for order, node in enumerate(nodes):  # 전위순회 — 부모가 자식보다 먼저 온다.
        npath = tuple(_norm(lbl) for lbl in node["path"])
        parent_id = id_by_path.get(npath[:-1]) if len(npath) > 1 else None
        is_leaf = bool(node["is_leaf"])
        match = existing_by_path.get(npath)
        if match is not None:
            actual_id = match.id
            if _apply_match(match, node["label"], parent_id, order, is_leaf):
                updated += 1
            else:
                unchanged += 1
        else:
            actual_id = _erp_id("|".join(npath))
            # 중간(그룹/본부)은 cost_type=None, 말단 팀은 기존 동명 팀의 비용구분(없으면 제조원가).
            cost_type = None if not is_leaf else (costtype_by_label.get(npath[-1]) or COST_TYPE_MFG)
            session.add(
                OrgUnit(
                    id=actual_id,
                    label=node["label"],
                    parent_id=parent_id,
                    cost_type=cost_type,
                    sort_order=order,
                )
            )
            added.append(node["label"])
        id_by_path[npath] = actual_id
        seen_ids.add(actual_id)

    await session.flush()  # 신규/변경을 먼저 확정한 뒤 prune(삭제 순서를 명시적으로 못박는다).

    # prune — ERP 에 없는 로컬 행 삭제(미러링). SQLite 는 SET NULL/CASCADE 미강제라 명시적으로 처리.
    stale = [o for o in existing if o.id not in seen_ids]
    deleted = [o.label for o in stale]
    if stale:
        stale_ids = [o.id for o in stale]
        await session.execute(
            update(User).where(User.org_unit_id.in_(stale_ids)).values(org_unit_id=None)
        )
        await session.execute(
            delete(AgentOrgAccess).where(AgentOrgAccess.org_unit_id.in_(stale_ids))
        )
        await session.execute(delete(OrgUnit).where(OrgUnit.id.in_(stale_ids)))

    await session.flush()
    return {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "deleted": deleted,
        "total": len(nodes),
    }


def _leaf_ids(org_units: list[OrgUnit]) -> set[str]:
    """말단(leaf) org_unit id 집합 — 다른 어떤 org_unit 의 parent 도 아닌 행(=배정 대상 팀).

    이제 본부/그룹은 중간 계층이므로, 멤버 배정·부서 매칭은 leaf 에만 건다.
    """
    parent_ids = {o.parent_id for o in org_units if o.parent_id is not None}
    return {o.id for o in org_units if o.id not in parent_ids}


async def match_org_unit_for_department(session: AsyncSession, department: object) -> OrgUnit | None:
    """부서명(ERP)을 org_units 라벨에 정규화 매칭 — 말단(leaf) 우선, 없으면 아무 매칭. 없으면 None.

    가입·로그인 시 사용자 소속(org_unit_id)을 부서(=조직구분)로 자동 배정하는 단건 조회.
    부서와 조직구분은 같은 개념이라, 부서 문자열이 조직구분 라벨과 정규화 일치하면 그 조직으로 잇는다.
    """
    n = _norm(department)
    if not n:
        return None
    org_units = (await session.execute(select(OrgUnit))).scalars().all()
    leaf_ids = _leaf_ids(org_units)
    leaf: OrgUnit | None = None
    fallback: OrgUnit | None = None
    for o in org_units:
        if _norm(o.label) != n:
            continue
        if o.id in leaf_ids and leaf is None:
            leaf = o
        if fallback is None:
            fallback = o
    return leaf or fallback


async def reconcile_users(session: AsyncSession) -> list[dict]:
    """department 있는 사용자를 org_unit 라벨에 정규화 매칭해 org_unit_id 재배치. 반환은 변경 목록.

    매칭은 말단(leaf) 우선, 없으면 아무 매칭 폴백. 매칭돼 소속이 달라질 때만 갱신한다.
    매칭 안 되는 사용자는 그대로 둔다. commit 은 호출자가 한다.
    """
    org_units = (
        (await session.execute(select(OrgUnit).order_by(OrgUnit.sort_order.asc(), OrgUnit.id.asc())))
        .scalars()
        .all()
    )
    leaf_ids = _leaf_ids(org_units)
    leaf_by_norm: dict[str, OrgUnit] = {}
    any_by_norm: dict[str, OrgUnit] = {}
    for o in org_units:
        n = _norm(o.label)
        any_by_norm.setdefault(n, o)
        if o.id in leaf_ids:
            leaf_by_norm.setdefault(n, o)

    users = (
        (await session.execute(select(User).where(User.department.is_not(None)))).scalars().all()
    )
    changes: list[dict] = []
    for u in users:
        n = _norm(u.department)
        if not n:
            continue
        target = leaf_by_norm.get(n) or any_by_norm.get(n)
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
