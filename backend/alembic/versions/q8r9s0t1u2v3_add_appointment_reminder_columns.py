"""add appointment reminder idempotency columns

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-06-30 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("due_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "due_notified_at")
    op.drop_column("appointments", "reminder_sent_at")
