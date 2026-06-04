"""add_lead_interaction_table

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-04 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_interactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pendente", nullable=False),
        sa.Column("devolutiva", sa.Text(), nullable=True),
        sa.Column("data_acionamento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_ultimo_contato", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interaction_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_lead_interactions_lead_id", "lead_interactions", ["lead_id"], unique=False)
    op.create_index("idx_lead_interactions_campaign_id", "lead_interactions", ["campaign_id"], unique=False)
    op.create_index("idx_lead_interactions_status", "lead_interactions", ["status"], unique=False)
    op.create_index(
        "idx_lead_interactions_data_acionamento",
        "lead_interactions",
        ["data_acionamento"],
        unique=False,
    )

    op.alter_column("lead_interactions", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_lead_interactions_data_acionamento", table_name="lead_interactions")
    op.drop_index("idx_lead_interactions_status", table_name="lead_interactions")
    op.drop_index("idx_lead_interactions_campaign_id", table_name="lead_interactions")
    op.drop_index("idx_lead_interactions_lead_id", table_name="lead_interactions")
    op.drop_table("lead_interactions")
