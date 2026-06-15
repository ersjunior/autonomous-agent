"""add WhatsApp delivery tracking fields to lead_interactions

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-06-14 22:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lead_interactions",
        sa.Column(
            "twilio_message_sid",
            sa.String(length=64),
            nullable=True,
            comment="Message SID Twilio (WhatsApp) para status callback de entrega.",
        ),
    )
    op.create_index(
        "ix_lead_interactions_twilio_message_sid",
        "lead_interactions",
        ["twilio_message_sid"],
    )
    op.add_column(
        "lead_interactions",
        sa.Column(
            "last_delivery_status",
            sa.String(length=32),
            nullable=True,
            comment="Status de entrega do provedor (queued/sent/delivered/failed…).",
        ),
    )
    op.add_column(
        "lead_interactions",
        sa.Column(
            "last_delivery_error_code",
            sa.String(length=16),
            nullable=True,
            comment="ErrorCode Twilio quando entrega falha (ex: 63015 sandbox).",
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_interactions", "last_delivery_error_code")
    op.drop_column("lead_interactions", "last_delivery_status")
    op.drop_index("ix_lead_interactions_twilio_message_sid", table_name="lead_interactions")
    op.drop_column("lead_interactions", "twilio_message_sid")
