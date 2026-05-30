"""initial_schema

Revision ID: e4a0f4a53be1
Revises: 
Create Date: 2026-05-30 18:51:04.692687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4a0f4a53be1'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    agent_mode = postgresql.ENUM("ACTIVE", "RECEPTIVE", name="agent_mode")
    channel_type = postgresql.ENUM(
        "WHATSAPP", "TELEGRAM", "VOICE", "VIDEO", name="channel_type"
    )
    agent_mode.create(op.get_bind(), checkfirst=True)
    channel_type.create(op.get_bind(), checkfirst=True)

    agent_mode_col = postgresql.ENUM(
        "ACTIVE", "RECEPTIVE", name="agent_mode", create_type=False
    )
    channel_type_col = postgresql.ENUM(
        "WHATSAPP", "TELEGRAM", "VOICE", "VIDEO", name="channel_type", create_type=False
    )

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mode", agent_mode_col, nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agents_user_id"), "agents", ["user_id"], unique=False)

    op.create_table(
        "channels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", channel_type_col, nullable=False),
        sa.Column("credentials", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_channels_user_id"), "channels", ["user_id"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_leads_user_id"), "leads", ["user_id"], unique=False)

    op.create_table(
        "campaigns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("channel_type", channel_type_col, nullable=False),
        sa.Column("leads_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaigns_agent_id"), "campaigns", ["agent_id"], unique=False)
    op.create_index(op.f("ix_campaigns_user_id"), "campaigns", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_campaigns_user_id"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_agent_id"), table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_index(op.f("ix_leads_user_id"), table_name="leads")
    op.drop_table("leads")
    op.drop_index(op.f("ix_channels_user_id"), table_name="channels")
    op.drop_table("channels")
    op.drop_index(op.f("ix_agents_user_id"), table_name="agents")
    op.drop_table("agents")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    sa.Enum(name="channel_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="agent_mode").drop(op.get_bind(), checkfirst=True)