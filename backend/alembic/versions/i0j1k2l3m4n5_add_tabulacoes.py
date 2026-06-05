"""add_tabulacoes

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-06-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tabulacoes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_tabulacoes_codigo"),
    )
    op.create_index("ix_tabulacoes_user_id", "tabulacoes", ["user_id"])

    op.add_column(
        "lead_interactions",
        sa.Column("tabulacao_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "lead_interactions",
        sa.Column("tabulacao_origem", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lead_interactions",
        sa.Column("tabulacao_aplicada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lead_interactions",
        sa.Column("twilio_call_sid", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_lead_interactions_tabulacao_id",
        "lead_interactions",
        "tabulacoes",
        ["tabulacao_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lead_interactions_tabulacao_id",
        "lead_interactions",
        ["tabulacao_id"],
    )
    op.create_index(
        "ix_lead_interactions_twilio_call_sid",
        "lead_interactions",
        ["twilio_call_sid"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_interactions_twilio_call_sid", table_name="lead_interactions")
    op.drop_index("ix_lead_interactions_tabulacao_id", table_name="lead_interactions")
    op.drop_constraint(
        "fk_lead_interactions_tabulacao_id",
        "lead_interactions",
        type_="foreignkey",
    )
    op.drop_column("lead_interactions", "twilio_call_sid")
    op.drop_column("lead_interactions", "tabulacao_aplicada_em")
    op.drop_column("lead_interactions", "tabulacao_origem")
    op.drop_column("lead_interactions", "tabulacao_id")
    op.drop_index("ix_tabulacoes_user_id", table_name="tabulacoes")
    op.drop_table("tabulacoes")
