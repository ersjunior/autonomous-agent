"""alter_interactions_embedding_dimensions

Revision ID: a7b8c9d0e1f2
Revises: f1b2c3d4e5f6
Create Date: 2026-05-31 12:00:00.000000

"""
from __future__ import annotations

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_INDEX = "ix_interactions_embedding"
_DEFAULT_DIMENSIONS = 1536


def _current_embedding_dimensions(connection: sa.Connection) -> int | None:
    row = connection.execute(
        sa.text(
            """
            SELECT format_type(a.atttypid, a.atttypmod) AS col_type
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relname = 'interactions'
              AND a.attname = 'embedding'
              AND n.nspname = 'public'
              AND NOT a.attisdropped
            """
        )
    ).fetchone()
    if row is None:
        return None
    match = re.fullmatch(r"vector\((\d+)\)", row.col_type)
    return int(match.group(1)) if match else None


def _apply_embedding_dimensions(target_dims: int) -> None:
    connection = op.get_bind()
    current_dims = _current_embedding_dimensions(connection)

    if current_dims == target_dims:
        return

    op.drop_index(_EMBEDDING_INDEX, table_name="interactions")

    # Embeddings existentes são incompatíveis com nova dimensão (ex.: OpenAI 1536 → Ollama 768).
    op.execute(sa.text("TRUNCATE TABLE interactions"))

    if current_dims is not None:
        op.alter_column(
            "interactions",
            "embedding",
            existing_type=Vector(current_dims),
            type_=Vector(target_dims),
            existing_nullable=False,
        )
    else:
        op.alter_column(
            "interactions",
            "embedding",
            type_=Vector(target_dims),
            existing_nullable=False,
        )

    op.execute(
        sa.text(
            f"CREATE INDEX {_EMBEDDING_INDEX} "
            "ON interactions USING hnsw (embedding vector_cosine_ops)"
        )
    )


def upgrade() -> None:
    _apply_embedding_dimensions(settings.embedding_dimensions)


def downgrade() -> None:
    _apply_embedding_dimensions(_DEFAULT_DIMENSIONS)
