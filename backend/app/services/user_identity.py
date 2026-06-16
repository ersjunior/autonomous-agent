"""Identidade institucional por usuário (workspace) — app_settings scope=user."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.identity import IDENTITY_FIELD_KEYS
from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

USER_SCOPE = "user"
INSTITUTIONAL_IDENTITY_KEY = "institutional_identity"


def _normalize_identity_payload(identity: dict[str, Any]) -> dict[str, str]:
    """Mantém apenas campos conhecidos com valores não vazios."""
    if not identity:
        return {}
    result: dict[str, str] = {}
    for key in IDENTITY_FIELD_KEYS:
        raw = identity.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            result[key] = text
    return result


def _parse_identity_value(raw: str | None) -> dict[str, str] | None:
    if not raw or not str(raw).strip():
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("institutional_identity JSON inválido; ignorando")
        return None
    if not isinstance(parsed, dict):
        return None
    normalized = _normalize_identity_payload(parsed)
    return normalized or None


async def load_user_identity(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, str] | None:
    """Lê identidade do workspace (scope=user). Retorna None se ausente ou vazia."""
    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == USER_SCOPE,
            AppSetting.user_id == user_id,
            AppSetting.key == INSTITUTIONAL_IDENTITY_KEY,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _parse_identity_value(row.value)


async def save_user_identity(
    session: AsyncSession,
    user_id: uuid.UUID,
    identity: dict[str, Any],
) -> None:
    """Persiste identidade do workspace (upsert). Usado pela API na fase 2b."""
    normalized = _normalize_identity_payload(identity)
    serialized = json.dumps(normalized, ensure_ascii=False) if normalized else "{}"

    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == USER_SCOPE,
            AppSetting.user_id == user_id,
            AppSetting.key == INSTITUTIONAL_IDENTITY_KEY,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        session.add(
            AppSetting(
                scope=USER_SCOPE,
                user_id=user_id,
                key=INSTITUTIONAL_IDENTITY_KEY,
                value=serialized,
                is_secret=False,
                updated_at=now,
            )
        )
        return

    row.value = serialized
    row.updated_at = now
