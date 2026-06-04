"""add_activation_and_channel_settings

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_channel_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "channel_type", name="uq_agent_channel_settings_agent_channel"),
    )
    op.create_index(
        "ix_agent_channel_settings_agent_id",
        "agent_channel_settings",
        ["agent_id"],
        unique=False,
    )

    op.create_table(
        "agent_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "channel_type", name="uq_agent_activations_campaign_channel"),
    )
    op.create_index("ix_agent_activations_agent_id", "agent_activations", ["agent_id"], unique=False)
    op.create_index(
        "ix_agent_activations_campaign_id",
        "agent_activations",
        ["campaign_id"],
        unique=False,
    )
    op.alter_column("agent_activations", "is_running", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_agent_activations_campaign_id", table_name="agent_activations")
    op.drop_index("ix_agent_activations_agent_id", table_name="agent_activations")
    op.drop_table("agent_activations")
    op.drop_index("ix_agent_channel_settings_agent_id", table_name="agent_channel_settings")
    op.drop_table("agent_channel_settings")
