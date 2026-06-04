"""add_is_system_and_source

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-06-04 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

lead_base_source = sa.Enum("IMPORT", "MANUAL", name="lead_base_source")


def upgrade() -> None:
    for table in ("agents", "channels", "campaigns", "leads"):
        op.add_column(
            table,
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    op.add_column(
        "lead_bases",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    lead_base_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "lead_bases",
        sa.Column(
            "source",
            lead_base_source,
            nullable=False,
            server_default="MANUAL",
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_bases", "source")
    lead_base_source.drop(op.get_bind(), checkfirst=True)
    op.drop_column("lead_bases", "is_system")
    for table in ("leads", "campaigns", "channels", "agents"):
        op.drop_column(table, "is_system")
