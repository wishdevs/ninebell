"""org_units 2뎁스(parent_id) + 비용구분(cost_type) + 계층 전체 재시드

Revision ID: 0011_org_units_hierarchy_cost
Revises: 0010_favorite_is_default
Create Date: 2026-07-03

기존 flat 7개(+배정된 멤버/에이전트접근)를 전체 재시드한다(사용자 확정: '전체 재시드').
org_units 삭제 시 agent_org_access 는 CASCADE, users.org_unit_id 는 SET NULL 로 정리된다
→ 기존 배정은 초기화(재설정 필요). 이후 본부(parent_id NULL) → 팀(parent_id=본부) 계층을
비용구분(판관비/제조원가)과 함께 시드한다. 멤버·에이전트접근은 팀(leaf)에만 배정한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_org_units_hierarchy_cost"
down_revision: str | None = "0010_favorite_is_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SGA = "판관비"
MFG = "제조원가"

# (본부 slug, 본부 라벨, [ (팀 라벨, 비용구분), ... ])
_HIERARCHY: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("hq_sales_head", "영업본부장", [("영업본부장", SGA)]),
    ("hq_sales", "영업본부", [("영업팀", SGA), ("영업관리팀", SGA), ("CS팀", SGA)]),
    ("hq_mgmt", "경영본부", [
        ("인사기획팀", SGA), ("총무팀", SGA), ("회계팀", SGA),
        ("구매팀", MFG), ("자재팀", MFG), ("품질팀", MFG),
    ]),
    ("hq_imp_head", "IMP연구소 본부장", [("IMP연구소 본부장", SGA)]),
    ("hq_imp_group", "IMP연구소 그룹장", [("IMP연구소 그룹장", SGA)]),
    ("hq_imp", "IMP연구소", [("IMP1팀", SGA), ("IMP2팀", SGA), ("IMP3팀", SGA)]),
    ("hq_fa_head", "FA연구소 본부장", [("FA연구소 본부장", MFG)]),
    ("hq_fa_advisor", "FA고문", [("FA고문", MFG)]),
    ("hq_fa", "FA연구소", [("연구기획팀", MFG)]),
    ("hq_fa_design", "FA연구소 (설계그룹)", [("설계1팀", MFG), ("설계2팀", MFG), ("설계3팀", MFG)]),
    ("hq_fa_control", "FA연구소 (제어그룹)", [("전장팀", MFG), ("제어1팀", MFG), ("제어2팀", MFG)]),
    ("hq_exec", "임원", [("임원실", SGA)]),
    ("hq_mfg", "제조본부", [
        ("제조1-A팀", MFG), ("제조1-B팀", MFG), ("제조1-전장팀", MFG),
        ("로봇팀", MFG), ("제조2팀", MFG), ("생산관리팀", MFG),
    ]),
    ("hq_mfg_advisor", "제조고문", [("제조고문", MFG)]),
]


def _seed_rows() -> list[dict]:
    rows: list[dict] = []
    for hq_i, (hq_slug, hq_label, teams) in enumerate(_HIERARCHY):
        rows.append({
            "id": hq_slug, "label": hq_label,
            "parent_id": None, "cost_type": None, "sort_order": hq_i,
        })
        for t_i, (team_label, cost) in enumerate(teams):
            rows.append({
                "id": f"{hq_slug}__t{t_i}", "label": team_label,
                "parent_id": hq_slug, "cost_type": cost, "sort_order": t_i,
            })
    return rows


def upgrade() -> None:
    op.add_column(
        "org_units",
        sa.Column(
            "parent_id", sa.String(length=40),
            sa.ForeignKey("org_units.id", ondelete="CASCADE"), nullable=True,
        ),
    )
    op.add_column("org_units", sa.Column("cost_type", sa.String(length=20), nullable=True))
    op.create_index("ix_org_units_parent_id", "org_units", ["parent_id"])

    # 전체 재시드 — 기존 flat 7개 삭제(agent_org_access CASCADE, users.org_unit_id SET NULL).
    op.execute("DELETE FROM org_units")

    org_units = sa.table(
        "org_units",
        sa.column("id", sa.String),
        sa.column("label", sa.String),
        sa.column("parent_id", sa.String),
        sa.column("cost_type", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(org_units, _seed_rows())


def downgrade() -> None:
    # 계층 시드 제거 후 컬럼 롤백. 원 flat 시드는 복원하지 않는다(0005 재실행 필요).
    op.execute("DELETE FROM org_units")
    op.drop_index("ix_org_units_parent_id", table_name="org_units")
    op.drop_column("org_units", "cost_type")
    op.drop_column("org_units", "parent_id")
