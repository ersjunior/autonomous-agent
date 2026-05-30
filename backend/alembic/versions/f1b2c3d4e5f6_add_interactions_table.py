"""add_interactions_table

Revision ID: f1b2c3d4e5f6
Revises: e4a0f4a53be1
Create Date: 2026-05-30 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "e4a0f4a53be1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "interactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=100), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interactions_user_id"), "interactions", ["user_id"], unique=False
    )
    op.execute(
        "CREATE INDEX ix_interactions_embedding "
        "ON interactions USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_embedding", table_name="interactions")
    op.drop_index(op.f("ix_interactions_user_id"), table_name="interactions")
    op.drop_table("interactions")
