"""org_apply — ERP 조직도(전체 깊이) → org_units 멱등 미러링 + 사용자 재배치 테스트.

seed_all 로 조직구분 2뎁스 시드가 미리 있다(경영본부/hq_mgmt·인사기획팀/hq_mgmt__t0 등).
apply_org_tree(nodes): 다단계 부모체인 upsert·멱등(경로해시로 id 안정)·기존 cost_type 보존·
동명 팀 cost_type 상속·prune(ERP 미포함 로컬 삭제 + 사용자 NULL·에이전트 접근 제거).
reconcile_users/match_org_unit_for_department: 부서 → 말단(leaf) 우선 매칭.
org_unit 동기화 가드(관리자+실 ERP 계정)도 함께 검증한다.
"""

from __future__ import annotations

from sqlalchemy import func, select

import app.services.code_sync as code_sync
import app.services.org_sync as org_sync
from app.models import AgentOrgAccess, OrgUnit, User
from app.services.org_apply import (
    _has_own_member_ids,
    _norm,
    apply_org_tree,
    match_org_unit_for_department,
    reconcile_users,
)


def _node(path: list[str], is_leaf: bool, count: int | None = None) -> dict:
    """손으로 짜는 전위순회 노드 — path 마지막이 self 라벨. build_full_tree 반환 형태."""
    return {"path": path, "label": path[-1], "count": count, "is_leaf": is_leaf}


async def _seed_id(sm, label: str) -> str:
    """시드 org_unit id 를 라벨로 조회(정규화 일치, 말단 우선).

    시드가 옛 slug(hq_mgmt__t0 등) 대신 경로해시 id 를 쓰므로, 테스트는 하드코딩 대신
    라벨로 실제 시드 id 를 뽑아 쓴다. 같은 라벨이 중간·말단에 겹치면 말단을 우선한다.
    """
    async with sm() as s:
        rows = (await s.execute(select(OrgUnit))).scalars().all()
    n = _norm(label)
    parent_ids = {o.parent_id for o in rows if o.parent_id}
    fallback: str | None = None
    for o in rows:
        if _norm(o.label) != n:
            continue
        if o.id not in parent_ids:  # 말단 우선
            return o.id
        fallback = fallback or o.id
    if fallback is None:
        raise AssertionError(f"시드에 '{label}' 라벨의 org_unit 이 없습니다.")
    return fallback


# ── apply_org_tree — 다단계 upsert ─────────────────────────────────────────────
async def test_apply_multilevel_chain_and_new_costtypes(sm):
    """기존 본부(경영본부) 밑에 신설 그룹→팀 부모체인 생성. 신규 말단=None(미선택)·중간=None."""
    seed_hq_id = await _seed_id(sm, "경영본부")  # 시드 본부(재사용 대상)
    # 신설 라벨을 써 '신규 생성' 동작을 검증한다(시드에 이미 있는 재무자원관리그룹/자재팀은 재사용이라 added 아님).
    nodes = [
        _node(["경영본부"], is_leaf=False, count=8),
        _node(["경영본부", "신설그룹"], is_leaf=False, count=5),
        _node(["경영본부", "신설그룹", "신설팀"], is_leaf=True, count=5),
    ]
    async with sm() as s:
        summary = await apply_org_tree(s, nodes)
        await s.commit()

    async with sm() as s:
        rows = (await s.execute(select(OrgUnit))).scalars().all()
        by_label = {o.label: o for o in rows}
        hq, grp, team = by_label["경영본부"], by_label["신설그룹"], by_label["신설팀"]
        assert hq.id == seed_hq_id  # 시드 경영본부 재사용(id 불변)
        assert hq.parent_id is None
        assert grp.parent_id == hq.id  # 중간 그룹이 본부 밑에
        assert grp.cost_type is None  # 상속할 동명 비용구분 없음 → None
        assert team.parent_id == grp.id  # 말단 팀이 그룹 밑에(전체 깊이 보존)
        assert team.cost_type is None  # 신규 말단 팀 = 미선택(None) — 제조원가 임의 기본값 아님
        # 신규 삽입 시 member_count(ERP 인원수) 저장.
        assert grp.member_count == 5
        assert team.member_count == 5

    assert summary["total"] == 3
    assert "신설그룹" in summary["added"]
    assert "신설팀" in summary["added"]
    assert "경영본부" not in summary["added"]  # 재사용은 added 아님


async def test_apply_is_idempotent(sm):
    """같은 nodes 두 번 반영해도 중복 없음 — 경로 해시로 id 안정."""
    nodes = [
        _node(["미래전략본부"], is_leaf=False),
        _node(["미래전략본부", "신사업팀"], is_leaf=True),
    ]
    async with sm() as s:
        first = await apply_org_tree(s, nodes)
        await s.commit()
    assert "미래전략본부" in first["added"] and "신사업팀" in first["added"]

    async with sm() as s:
        rows1 = {o.label: o.id for o in (await s.execute(select(OrgUnit))).scalars().all()}

    async with sm() as s:
        second = await apply_org_tree(s, nodes)
        await s.commit()

    async with sm() as s:
        rows2 = {o.label: o.id for o in (await s.execute(select(OrgUnit))).scalars().all()}

    assert rows1 == rows2  # 라벨·id 동일(새 행 없음, id 안정)
    assert second["added"] == []  # 두 번째엔 추가 0


async def test_apply_reuse_preserves_existing_costtype(sm):
    """경로가 매칭되는 기존 팀은 재사용 — id·cost_type 보존(제조원가로 덮지 않음)."""
    hr_id = await _seed_id(sm, "인사/기획팀")  # 시드 인사/기획팀(판관비)
    hq_id = await _seed_id(sm, "경영본부")
    nodes = [
        _node(["경영본부"], is_leaf=False),
        _node(["경영본부", "인사기획팀"], is_leaf=True),  # 시드 인사/기획팀에 정규화 매칭
    ]
    async with sm() as s:
        await apply_org_tree(s, nodes)
        await s.commit()
    async with sm() as s:
        team = await s.get(OrgUnit, hr_id)
        assert team is not None
        assert team.id == hr_id  # id 불변
        assert team.cost_type == "판관비"  # 기존 비용구분 보존
        assert team.parent_id == hq_id


async def test_apply_moved_leaf_inherits_costtype(sm):
    """재편으로 경로가 달라진 동명 팀(신규 행)은 기존 팀의 cost_type 을 따라간다."""
    # 시드 회계팀(hq_mgmt__t2, 판관비)을 '재무그룹' 아래로 재편 — 경로가 달라 신규지만 판관비 상속.
    nodes = [
        _node(["경영본부"], is_leaf=False),
        _node(["경영본부", "재무그룹"], is_leaf=False),
        _node(["경영본부", "재무그룹", "회계팀"], is_leaf=True),
    ]
    async with sm() as s:
        await apply_org_tree(s, nodes)
        await s.commit()
    async with sm() as s:
        rows = (await s.execute(select(OrgUnit))).scalars().all()
        acct = next(o for o in rows if o.label == "회계팀")
        grp = next(o for o in rows if o.label == "재무그룹")
        assert acct.parent_id == grp.id
        assert acct.id != "hq_mgmt__t2"  # 경로가 달라 신규 행(id 다름)
        assert acct.cost_type == "판관비"  # 제조원가 기본이 아니라 시드 회계팀 상속


async def test_apply_prunes_absent_orgs(sm):
    """ERP 트리에 없는 로컬 org_unit 은 삭제 — 사용자 org_unit_id=NULL·에이전트 접근 제거."""
    # 시드 영업팀에 사용자·에이전트 접근을 걸어 둔다(ERP 트리에 없어 prune 대상).
    sales_team_id = await _seed_id(sm, "영업팀")
    uid = await _add_user(sm, "emp-prune", None, org_unit_id=sales_team_id)
    async with sm() as s:
        s.add(AgentOrgAccess(agent_id="agent-x", org_unit_id=sales_team_id))
        await s.commit()

    nodes = [
        _node(["경영본부"], is_leaf=False),
        _node(["경영본부", "인사기획팀"], is_leaf=True),
    ]
    async with sm() as s:
        summary = await apply_org_tree(s, nodes)
        await s.commit()

    async with sm() as s:
        assert await s.get(OrgUnit, sales_team_id) is None  # 삭제됨
        u = await s.get(User, uid)
        assert u.org_unit_id is None  # 사용자 소속 해제(SET NULL 명시 처리)
        acc = (
            (
                await s.execute(
                    select(AgentOrgAccess).where(AgentOrgAccess.org_unit_id == sales_team_id)
                )
            )
            .scalars()
            .all()
        )
        assert acc == []  # 에이전트 접근 제거
    assert "영업팀" in summary["deleted"]


# ── reconcile_users / match_org_unit_for_department — 말단(leaf) 우선 ────────────
async def _add_user(sm, userid: str, department: str | None, org_unit_id: str | None = None):
    async with sm() as s:
        u = User(
            omnisol_userid=userid,
            display_name=userid,
            department=department,
            org_unit_id=org_unit_id,
            status="active",
        )
        s.add(u)
        await s.commit()
        return u.id


async def test_reconcile_matches_across_slash_normalization(sm):
    """department '인사/기획팀' → org_unit '인사기획팀'(hq_mgmt__t0) 로 정규화 매칭."""
    hr_id = await _seed_id(sm, "인사/기획팀")
    uid = await _add_user(sm, "emp-hr", "인사/기획팀")
    async with sm() as s:
        changes = await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        assert u.org_unit_id == hr_id
    assert any(c["userid"] == "emp-hr" and c["to"] == hr_id for c in changes)


async def test_reconcile_moves_user_from_existing_org(sm):
    """소속이 이미 있어도 department 가 다른 팀을 가리키면 재배치한다."""
    sales_team_id = await _seed_id(sm, "영업팀")
    acct_id = await _seed_id(sm, "회계팀")
    uid = await _add_user(sm, "emp-acct", "회계팀", org_unit_id=sales_team_id)
    async with sm() as s:
        changes = await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        assert u.org_unit_id == acct_id  # 회계팀
    ch = next(c for c in changes if c["userid"] == "emp-acct")
    assert ch["from"] == sales_team_id and ch["to"] == acct_id


async def test_reconcile_leaves_unmatched_unchanged(sm):
    """어느 조직 라벨과도 매칭 안 되는 department 는 org_unit_id 를 건드리지 않는다."""
    uid = await _add_user(sm, "emp-x", "존재하지않는부서")
    async with sm() as s:
        changes = await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        assert u.org_unit_id is None
    assert all(c["userid"] != "emp-x" for c in changes)


async def test_department_resolves_to_leaf_not_intermediate(sm):
    """같은 라벨이 중간 계층과 말단에 모두 있을 때, 부서는 직속 인원 보유 노드(=말단 설계)로 배정된다."""
    # '설계'가 중간(연구소>설계)과 말단(연구소>설계>설계) 둘 다로 등장하는 트리를 반영.
    # 인원수: 연구소 5 = 중간 설계 5(직속 0), 중간 설계 5 = 말단 설계 5(직속 0), 말단 설계 5(직속 5).
    # → 직속 인원을 가진 건 말단 설계뿐이라, '설계' 부서는 말단으로 배정된다.
    nodes = [
        _node(["연구소"], is_leaf=False, count=5),
        _node(["연구소", "설계"], is_leaf=False, count=5),  # 중간 '설계'(자식 있음, 직속 0)
        _node(["연구소", "설계", "설계"], is_leaf=True, count=5),  # 말단 '설계'(직속 5)
    ]
    async with sm() as s:
        await apply_org_tree(s, nodes)
        await s.commit()

    async with sm() as s:
        all_units = (await s.execute(select(OrgUnit))).scalars().all()
        parent_ids = {o.parent_id for o in all_units if o.parent_id}
        matched = await match_org_unit_for_department(s, "설계")
        assert matched is not None
        assert matched.id not in parent_ids  # 말단(다른 org 의 부모가 아님)

    # reconcile_users 도 동일하게 말단으로 배정한다.
    uid = await _add_user(sm, "emp-design", "설계")
    async with sm() as s:
        await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        all_units = (await s.execute(select(OrgUnit))).scalars().all()
        parent_ids = {o.parent_id for o in all_units if o.parent_id}
        assert u.org_unit_id is not None
        assert u.org_unit_id not in parent_ids  # 말단으로 배정


async def test_has_own_member_ids_includes_member_bearing_group(sm):
    """직속 인원을 가진 중간 그룹은 own-member 에 포함, 순수 컨테이너(직속 0)는 제외.

    나인벨 실측 구조 축약: 경영본부 11 = 재무자원관리그룹 11(본부 직속 0=순수 컨테이너),
    재무자원관리그룹 11 - 자식합(자재3+회계4+총무3=10) = 직속 1 → 배정 대상(말단 팀뿐 아님).
    apply_org_tree 가 member_count 를 저장하는 것도 함께 확인한다.
    """
    nodes = [
        _node(["경영본부"], is_leaf=False, count=11),
        _node(["경영본부", "재무자원관리그룹"], is_leaf=False, count=11),
        _node(["경영본부", "재무자원관리그룹", "자재팀"], is_leaf=True, count=3),
        _node(["경영본부", "재무자원관리그룹", "회계팀"], is_leaf=True, count=4),
        _node(["경영본부", "재무자원관리그룹", "총무팀"], is_leaf=True, count=3),
    ]
    async with sm() as s:
        await apply_org_tree(s, nodes)
        await s.commit()

    async with sm() as s:
        rows = (await s.execute(select(OrgUnit))).scalars().all()
    by_label = {o.label: o for o in rows}
    own = _has_own_member_ids(rows)

    # apply 가 인원수(member_count)를 저장했는지.
    assert by_label["경영본부"].member_count == 11
    assert by_label["재무자원관리그룹"].member_count == 11
    assert by_label["자재팀"].member_count == 3

    # 직속 인원 보유 판별.
    assert by_label["재무자원관리그룹"].id in own  # 직속 1 → 배정 대상(순수 컨테이너 아님)
    assert by_label["경영본부"].id not in own  # 직속 0 → 순수 컨테이너 제외
    assert by_label["자재팀"].id in own  # 말단 팀 → 포함
    # 부서 매칭도 그룹 노드로 이어진다(말단이 아니어도).
    async with sm() as s:
        matched = await match_org_unit_for_department(s, "재무자원관리그룹")
    assert matched is not None and matched.id == by_label["재무자원관리그룹"].id


def test_norm_handles_separators():
    assert _norm("인사/기획팀") == _norm("인사기획팀")
    assert _norm("경영 본부") == _norm("경영본부")
    # 괄호·하이픈 등 구분기호는 제거하되(‘내부 텍스트’는 보존), 대소문자는 접는다.
    assert _norm("제조1-A팀") == "제조1a팀"
    assert _norm("FA연구소 (설계그룹)") == "fa연구소설계그룹"


# ── org_unit 동기화 가드(관리자 + 실 ERP 계정) ──────────────────────────────────
async def test_org_sync_local_admin_rejected_400(client, auth_as, sm):
    """로컬 admin(password_hash 존재)은 실 ERP 로그인이 없어 org_unit 동기화 400."""
    async with sm() as s:
        admin = (
            await s.execute(select(User).where(User.omnisol_userid == "admin"))
        ).scalar_one()
        admin_id = admin.id
    auth_as(admin_id)
    resp = await client.post("/me/catalog/sync", json={"kind": "org_unit"})
    assert resp.status_code == 400
    assert "로컬 admin" in resp.json()["detail"]


async def test_org_sync_non_admin_rejected_403(client, make_user, auth_as):
    """user 롤은 org_unit 동기화 403."""
    uid = await make_user("erp-user", "user")
    auth_as(uid)
    resp = await client.post("/me/catalog/sync", json={"kind": "org_unit"})
    assert resp.status_code == 403


async def test_org_sync_real_erp_admin_passes_guard(client, make_user, auth_as):
    """실 ERP 관리자(password_hash 없음)는 가드를 통과 — 이후 자격증명 없음 409(400/403 아님)."""
    uid = await make_user("erp-admin", "admin")  # make_user 는 password_hash 미설정
    auth_as(uid)
    resp = await client.post("/me/catalog/sync", json={"kind": "org_unit"})
    assert resp.status_code == 409
    assert "자격증명" in resp.json()["error"]


# ── sync_catalog(org_unit) 요약 스루(fetch_org_tree 몽키패치) ────────────────────
async def test_sync_catalog_org_unit_threads_summary(sm, monkeypatch):
    """sync_catalog('org_unit') 이 org_units 반영(applied) + 사용자 재배치(reassigned) 요약을 반환."""
    hr_id = await _seed_id(sm, "인사/기획팀")
    await _add_user(sm, "emp-sync", "인사/기획팀")  # 재배치 대상

    async def _fake_tree(userid, password, browser_factory):  # noqa: ANN001
        return {
            "raw": [],
            "flat": [  # catalog(미리보기)는 flat 로 upsert.
                {"hq": "경영본부", "hqCount": 10, "team": "인사/기획팀", "teamCount": 3},
                {"hq": "미래전략본부", "hqCount": 4, "team": "신사업팀", "teamCount": 2},
            ],
            "nodes": [  # org_units 미러링은 전체 깊이 nodes 로.
                _node(["경영본부"], is_leaf=False),
                _node(["경영본부", "인사기획팀"], is_leaf=True),
                _node(["미래전략본부"], is_leaf=False),
                _node(["미래전략본부", "신사업팀"], is_leaf=True),
            ],
        }

    monkeypatch.setattr(org_sync, "fetch_org_tree", _fake_tree)

    async def _factory():  # fetch_org_tree 패치로 브라우저는 쓰이지 않는다.
        raise AssertionError("browser_factory 는 호출되지 않아야 한다")

    result = await code_sync.sync_catalog("org_unit", "u", "p", _factory, sm)
    assert result["count"] >= 2  # 카탈로그(본부+팀) 건수
    assert "미래전략본부" in result["applied"]["added"]
    assert "신사업팀" in result["applied"]["added"]
    assert result["applied"]["total"] == 4
    assert any(
        c["userid"] == "emp-sync" and c["to"] == hr_id for c in result["reassigned"]
    )

    # 실제 org_units 에도 신규 본부/팀이 반영됐는지 확인.
    async with sm() as s:
        labels = {o.label for o in (await s.execute(select(OrgUnit))).scalars().all()}
    assert {"미래전략본부", "신사업팀"} <= labels
