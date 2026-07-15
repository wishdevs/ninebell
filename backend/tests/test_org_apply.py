"""org_apply — ERP 조직도(본부▸팀) → org_units 멱등 반영 + 사용자 재배치 테스트.

seed_all 로 조직구분 2뎁스 시드가 미리 있다(경영본부/hq_mgmt·인사기획팀/hq_mgmt__t0 등).
apply_org_tree: 신규 생성·멱등·기존(id·cost_type) 보존·로컬 전용 미삭제.
reconcile_users: department 정규화 매칭('인사/기획팀'→'인사기획팀')·이동·무매칭 불변.
org_unit 동기화 가드(관리자+실 ERP 계정)도 함께 검증한다.
"""

from __future__ import annotations

from sqlalchemy import func, select

import app.services.code_sync as code_sync
import app.services.org_sync as org_sync
from app.models import OrgUnit, User
from app.services.org_apply import _norm, apply_org_tree, reconcile_users


# ── apply_org_tree ────────────────────────────────────────────────────────────
async def test_apply_creates_new_and_matches_existing(sm):
    """기존 라벨은 재사용(id·cost_type 보존), 신규 본부/팀은 생성, 로컬 전용은 삭제 안 함."""
    flat = [
        # 시드의 경영본부/인사기획팀과 정규화 매칭('인사/기획팀'==인사기획팀).
        {"hq": "경영본부", "hqCount": 10, "team": "인사/기획팀", "teamCount": 3},
        # 완전 신규 본부·팀.
        {"hq": "미래전략본부", "hqCount": 4, "team": "신사업팀", "teamCount": 2},
    ]
    async with sm() as s:
        summary = await apply_org_tree(s, flat)
        await s.commit()

    async with sm() as s:
        # 기존 인사기획팀 = id·cost_type 보존(라벨은 ERP 표기로 정정될 수 있음).
        team = await s.get(OrgUnit, "hq_mgmt__t0")
        assert team is not None
        assert team.id == "hq_mgmt__t0"  # id 불변
        assert team.cost_type == "판관비"  # cost_type 불변(ERP 엔 없음)
        assert team.parent_id == "hq_mgmt"

        rows = (await s.execute(select(OrgUnit))).scalars().all()
        labels = {o.label for o in rows}
        assert "미래전략본부" in labels
        assert "신사업팀" in labels
        # 신규 팀은 부모(미래전략본부)에 붙고 cost_type=None.
        new_hq = next(o for o in rows if o.label == "미래전략본부")
        new_team = next(o for o in rows if o.label == "신사업팀")
        assert new_team.parent_id == new_hq.id
        assert new_team.cost_type is None
        # 시드 본부/팀은 여전히 존재(ERP 미포함이어도 삭제 안 함).
        assert await s.get(OrgUnit, "hq_sales") is not None
        assert await s.get(OrgUnit, "hq_sales__t0") is not None  # 영업팀

    assert "미래전략본부" in summary["added"]
    assert "신사업팀" in summary["added"]
    # ERP 트리에 없던 시드 조직들이 local_only 로 보고된다(예: 영업팀).
    assert "영업팀" in summary["local_only"]
    assert summary["total_erp"] == 2


async def test_apply_is_idempotent(sm):
    """같은 flat 두 번 반영해도 중복 생성 없음(결정적 id + 라벨 매칭)."""
    flat = [{"hq": "알파본부", "hqCount": None, "team": "알파팀", "teamCount": None}]
    async with sm() as s:
        first = await apply_org_tree(s, flat)
        await s.commit()
    assert "알파본부" in first["added"] and "알파팀" in first["added"]

    async with sm() as s:
        before = (await s.execute(select(func.count()).select_from(OrgUnit))).scalar()

    async with sm() as s:
        second = await apply_org_tree(s, flat)
        await s.commit()

    async with sm() as s:
        after = (await s.execute(select(func.count()).select_from(OrgUnit))).scalar()

    assert before == after  # 새 행 없음
    assert second["added"] == []  # 두 번째엔 추가 0


async def test_apply_preserves_local_only_costtype_on_rerun(sm):
    """멱등 재실행에서 매칭된 기존 팀의 cost_type·id 가 여전히 보존된다."""
    flat = [{"hq": "경영본부", "hqCount": 10, "team": "회계팀", "teamCount": 5}]
    async with sm() as s:
        await apply_org_tree(s, flat)
        await apply_org_tree(s, flat)  # 두 번째도 같은 세션에서
        await s.commit()
    async with sm() as s:
        team = await s.get(OrgUnit, "hq_mgmt__t2")  # 시드 회계팀
        assert team is not None
        assert team.cost_type == "판관비"
        assert team.id == "hq_mgmt__t2"


# ── reconcile_users ───────────────────────────────────────────────────────────
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
    uid = await _add_user(sm, "emp-hr", "인사/기획팀")
    async with sm() as s:
        changes = await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        assert u.org_unit_id == "hq_mgmt__t0"
    assert any(c["userid"] == "emp-hr" and c["to"] == "hq_mgmt__t0" for c in changes)


async def test_reconcile_moves_user_from_existing_org(sm):
    """소속이 이미 있어도 department 가 다른 팀을 가리키면 재배치한다."""
    uid = await _add_user(sm, "emp-acct", "회계팀", org_unit_id="hq_sales__t0")
    async with sm() as s:
        changes = await reconcile_users(s)
        await s.commit()
    async with sm() as s:
        u = await s.get(User, uid)
        assert u.org_unit_id == "hq_mgmt__t2"  # 회계팀
    ch = next(c for c in changes if c["userid"] == "emp-acct")
    assert ch["from"] == "hq_sales__t0" and ch["to"] == "hq_mgmt__t2"


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
    await _add_user(sm, "emp-sync", "인사/기획팀")  # 재배치 대상

    async def _fake_tree(userid, password, browser_factory):  # noqa: ANN001
        return {
            "raw": [],
            "flat": [
                {"hq": "경영본부", "hqCount": 10, "team": "인사/기획팀", "teamCount": 3},
                {"hq": "미래전략본부", "hqCount": 4, "team": "신사업팀", "teamCount": 2},
            ],
        }

    monkeypatch.setattr(org_sync, "fetch_org_tree", _fake_tree)

    async def _factory():  # fetch_org_tree 패치로 브라우저는 쓰이지 않는다.
        raise AssertionError("browser_factory 는 호출되지 않아야 한다")

    result = await code_sync.sync_catalog("org_unit", "u", "p", _factory, sm)
    assert result["count"] >= 2  # 카탈로그(본부+팀) 건수
    assert "미래전략본부" in result["applied"]["added"]
    assert any(
        c["userid"] == "emp-sync" and c["to"] == "hq_mgmt__t0" for c in result["reassigned"]
    )

    # 실제 org_units 에도 신규 본부/팀이 반영됐는지 확인.
    async with sm() as s:
        labels = {o.label for o in (await s.execute(select(OrgUnit))).scalars().all()}
    assert {"미래전략본부", "신사업팀"} <= labels
