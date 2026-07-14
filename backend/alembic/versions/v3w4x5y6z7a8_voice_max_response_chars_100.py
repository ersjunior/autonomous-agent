"""align voice_max_response_chars to 100 (telephony brevity)

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-07-11 21:45:00.000000

Com barge-in off, respostas de ~150 chars geravam ~12s de fala. 100 chars (~2 frases)
limita a experiência a ~7–8s; o cap corta na última frase completa (sanitize).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, None] = "u2v3w4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOBAL_SCOPE = "global"
_KEY = "voice_max_response_chars"
_NEW_VALUE = "100"
_PREVIOUS_VALUE = "150"


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
    _update_global_setting(conn, _PREVIOUS_VALUE)
