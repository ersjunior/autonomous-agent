"""align voice_response_max_tokens to 256 (generous voice cap)

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-07-05 02:55:00.000000

Bancos existentes tinham voice_response_max_tokens=112 (cap telegráfico antigo).
O default em código passou a 256; o seed não sobrescreve chaves existentes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOBAL_SCOPE = "global"
_KEY = "voice_response_max_tokens"
_NEW_VALUE = "256"
_LEGACY_VALUE = "112"


def _update_global_setting(conn: sa.Connection, value: str) -> None:
    conn.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = :value,
                updated_at = NOW()
            WHERE scope = :scope
              AND user_id IS NULL
              AND key = :key
            """
        ),
        {"value": value, "scope": _GLOBAL_SCOPE, "key": _KEY},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _update_global_setting(conn, _NEW_VALUE)


def downgrade() -> None:
    conn = op.get_bind()
    _update_global_setting(conn, _LEGACY_VALUE)
