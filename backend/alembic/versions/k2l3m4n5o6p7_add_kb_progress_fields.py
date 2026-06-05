"""add kb document progress fields

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-06-05 12:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column("total_chunks_estimated", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "kb_documents",
        sa.Column("chunks_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("kb_documents", "chunks_processed")
    op.drop_column("kb_documents", "total_chunks_estimated")
