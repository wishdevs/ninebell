"""merchant_dict_rules 테이블 생성 + 코드 기본 사전 시드.

가맹점 분류 사전(하이브리드)을 DB 로 관리(화면 편집). 초기 규칙은 코드 기본 사전
(merchant_dict.DEFAULT_RULES)을 그대로 시드한다. 시드는 앱 코드에서 값을 읽어 넣되,
멱등(이미 있으면 스킵)하게 처리한다.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0025_merchant_dict_rules"
down_revision: str | None = "0024_fix_bare_name_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_dict_rules",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("keywords", sa.String(1024), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("acct", sa.String(120), nullable=True),
        sa.Column("strong", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(40), nullable=False, server_default="큐레이션"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 코드 기본 사전 시드 — 앱 상수에서 읽어 넣는다(멱등: 빈 테이블일 때만).
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM merchant_dict_rules")).scalar_one()
    if existing:
        return
    try:
        from app.agents.card_collect.merchant_dict import DEFAULT_RULES
    except Exception:  # noqa: BLE001 — import 실패 시 빈 테이블(앱 폴백이 코드 사전 사용).
        return
    for i, r in enumerate(DEFAULT_RULES):
        bind.execute(
            sa.text(
                "INSERT INTO merchant_dict_rules "
                "(id, keywords, category, acct, strong, source, sort_order, enabled) "
                "VALUES (:id, :kw, :cat, :acct, :strong, :src, :ord, true)"
            ),
            {
                "id": uuid.uuid4(),
                "kw": ",".join(r.keywords),
                "cat": r.category,
                "acct": r.acct,
                "strong": r.strong,
                "src": r.source,
                "ord": i * 10,
            },
        )


def downgrade() -> None:
    op.drop_table("merchant_dict_rules")
