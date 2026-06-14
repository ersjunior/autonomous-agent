"""remove VIDEO from channel_type enum

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-06-14 12:00:00.000000

Postgres não suporta ALTER TYPE ... DROP VALUE. Recria o enum com 3 valores
após garantir que channels.type não contém 'VIDEO' (limpeza de dados bloco 5).

Apenas channels.type usa o enum channel_type; demais tabelas usam varchar(50).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHANNEL_VALUES_NEW = ("WHATSAPP", "TELEGRAM", "VOICE")
_CHANNEL_VALUES_OLD = ("WHATSAPP", "TELEGRAM", "VOICE", "VIDEO")


def upgrade() -> None:
    values = ", ".join(f"'{v}'" for v in _CHANNEL_VALUES_NEW)
    op.execute(f"CREATE TYPE channel_type_new AS ENUM ({values})")
    op.execute(
        """
        ALTER TABLE channels
        ALTER COLUMN type TYPE channel_type_new
        USING type::text::channel_type_new
        """
    )
    op.execute("DROP TYPE channel_type")
    op.execute("ALTER TYPE channel_type_new RENAME TO channel_type")


def downgrade() -> None:
    values = ", ".join(f"'{v}'" for v in _CHANNEL_VALUES_OLD)
    op.execute(f"CREATE TYPE channel_type_old AS ENUM ({values})")
    op.execute(
        """
        ALTER TABLE channels
        ALTER COLUMN type TYPE channel_type_old
        USING type::text::channel_type_old
        """
    )
    op.execute("DROP TYPE channel_type")
    op.execute("ALTER TYPE channel_type_old RENAME TO channel_type")
