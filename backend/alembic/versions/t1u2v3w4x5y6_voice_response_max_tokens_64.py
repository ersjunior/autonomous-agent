"""align voice_response_max_tokens to 64 (concise voice cap)

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-07-10 21:00:00.000000

Respostas de voz longas (256 tokens) geravam TTS de dezenas de segundos.
64 tokens (~1–3 frases) força brevidade na telefonia; texto mantém response_max_tokens.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOBAL_SCOPE = "global"
_KEY = "voice_response_max_tokens"
_NEW_VALUE = "64"
_PREVIOUS_VALUE = "256"


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
