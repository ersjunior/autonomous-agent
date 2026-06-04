"""add_channel_name

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-06-04 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("name", sa.String(length=100), nullable=True))
    op.create_unique_constraint("uq_channels_user_name", "channels", ["user_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_channels_user_name", "channels", type_="unique")
    op.drop_column("channels", "name")
