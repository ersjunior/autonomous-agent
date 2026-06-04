"""add_app_settings_table

Revision ID: e5f6a7b8c9d0
Revises: c2d3e4f5a6b7
Create Date: 2026-06-04 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False, server_default="global"),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "user_id",
            "key",
            name="uq_app_settings_scope_user_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_app_settings_scope_key",
        "app_settings",
        ["scope", "key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_app_settings_scope_key", table_name="app_settings")
    op.drop_table("app_settings")
