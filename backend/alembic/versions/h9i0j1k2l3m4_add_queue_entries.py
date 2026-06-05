"""add_queue_entries

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-06-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_status_enum = postgresql.ENUM(
    "WAITING",
    "ANSWERED",
    "ABANDONED",
    name="queue_entry_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE queue_entry_status AS ENUM ('WAITING', 'ANSWERED', 'ABANDONED');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.create_table(
        "queue_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wait_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            _status_enum,
            nullable=False,
            server_default="WAITING",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queue_entries_channel_type", "queue_entries", ["channel_type"])
    op.create_index("ix_queue_entries_user_id", "queue_entries", ["user_id"])
    op.create_index("ix_queue_entries_status", "queue_entries", ["status"])
    op.create_index("ix_queue_entries_enqueued_at", "queue_entries", ["enqueued_at"])
    op.create_index("ix_queue_entries_lead_id", "queue_entries", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_queue_entries_lead_id", table_name="queue_entries")
    op.drop_index("ix_queue_entries_enqueued_at", table_name="queue_entries")
    op.drop_index("ix_queue_entries_status", table_name="queue_entries")
    op.drop_index("ix_queue_entries_user_id", table_name="queue_entries")
    op.drop_index("ix_queue_entries_channel_type", table_name="queue_entries")
    op.drop_table("queue_entries")
    op.execute("DROP TYPE IF EXISTS queue_entry_status")
