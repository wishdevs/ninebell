"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_permissions"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_id"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("omnisol_userid", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_users_role_id_roles", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("omnisol_userid", name="uq_users_omnisol_userid"),
    )
    op.create_index("ix_users_omnisol_userid", "users", ["omnisol_userid"], unique=True)
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.create_table(
        "access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("omnisol_userid", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_access_logs_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_logs"),
    )
    op.create_index("ix_access_logs_user_id", "access_logs", ["user_id"])
    op.create_index("ix_access_logs_omnisol_userid", "access_logs", ["omnisol_userid"])
    op.create_index("ix_access_logs_logged_at", "access_logs", ["logged_at"])

    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("drive", sa.String(length=32), nullable=False),
        sa.Column("interaction", sa.String(length=32), nullable=False),
        sa.Column("target_system", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("target_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow_graph", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("skill", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("substeps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_agent_steps_agent_id_agents", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_steps"),
    )
    op.create_index("ix_agent_steps_agent_id", "agent_steps", ["agent_id"])

    op.create_table(
        "agent_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("step_label", sa.String(length=255), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_agent_logs_agent_id_agents", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_logs"),
    )
    op.create_index("ix_agent_logs_agent_id", "agent_logs", ["agent_id"])

    op.create_table(
        "agent_interventions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("placeholder", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_interventions_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_interventions"),
        sa.UniqueConstraint("agent_id", name="uq_agent_interventions_agent_id"),
    )
    op.create_index("ix_agent_interventions_agent_id", "agent_interventions", ["agent_id"])


def downgrade() -> None:
    op.drop_table("agent_interventions")
    op.drop_table("agent_logs")
    op.drop_table("agent_steps")
    op.drop_table("agents")
    op.drop_table("access_logs")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
