"""add_interaction_attempts

Revision ID: g8h9i0j1k2l3
Revises: d4e5f6a7b8c9
Create Date: 2026-06-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lead_interactions",
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lead_interactions",
        sa.Column("data_ultima_tentativa", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE lead_interactions
        SET tentativas = 1,
            data_ultima_tentativa = COALESCE(data_acionamento, created_at)
        WHERE data_acionamento IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("lead_interactions", "data_ultima_tentativa")
    op.drop_column("lead_interactions", "tentativas")
