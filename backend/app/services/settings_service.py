"""Load and persist provider settings from PostgreSQL into the settings singleton."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import redis
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.services.settings_schema import (
    AGENT_SYSTEM_PROMPT_MAX_LENGTH,
    CATEGORY_LABELS,
    EDITABLE_KEYS,
    MANAGED_KEYS,
    MANAGED_SETTINGS,
    SCHEMA_BY_KEY,
    SettingCategory,
    SettingFieldSchema,
)

logger = logging.getLogger(__name__)

GLOBAL_SCOPE = "global"
SETTINGS_VERSION_KEY = "settings_version"
SETTINGS_INVALIDATE_CHANNEL = "settings_invalidate"
SECRET_MASK = "********"

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return SECRET_MASK
    return f"{value[:3]}...{value[-4:]}"


def _parse_numeric_string(raw: str, schema: SettingFieldSchema) -> int | float:
    stripped = raw.strip()
    if not stripped:
        raise ValueError("empty numeric value")
    if schema.value_type == "int":
        return int(float(stripped))
    if schema.value_type == "float":
        return float(stripped)
    raise ValueError(f"number field {schema.key} missing value_type in schema")


def _clamp_numeric(
    value: int | float, schema: SettingFieldSchema
) -> int | float:
    if schema.min_value is not None and value < schema.min_value:
        value = schema.min_value
    if schema.max_value is not None and value > schema.max_value:
        value = schema.max_value
    if schema.value_type == "int":
        return int(value)
    return float(value)


def _coerce_number(
    key: str,
    raw: str,
    *,
    clamp: bool = False,
) -> int | float:
    schema = SCHEMA_BY_KEY[key]
    if schema.field_type != "number":
        raise ValueError(f"{key} is not a number field")
    try:
        value = _parse_numeric_string(raw, schema)
    except ValueError as exc:
        raise ValueError(f"invalid numeric value for {key}: {raw!r}") from exc
    if clamp:
        return _clamp_numeric(value, schema)
    return value


def _coerce_value(key: str, raw: str | None, *, clamp_numbers: bool = False) -> Any:
    """Convert a DB/API string into the Python type declared in settings_schema."""
    if raw is None:
        return None
    schema = SCHEMA_BY_KEY.get(key)
    if schema is None:
        return raw

    if schema.field_type == "number":
        return _coerce_number(key, raw, clamp=clamp_numbers)

    if schema.field_type == "textarea":
        return raw

    return raw


def _serialize_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _apply_to_settings(key: str, value: Any) -> None:
    if not hasattr(settings, key):
        logger.warning("Skipping unknown settings key: %s", key)
        return
    setattr(settings, key, value)


def _publish_invalidation() -> int:
    """Increment Redis version and publish invalidation for other processes."""
    client = _get_redis()
    version = int(client.incr(SETTINGS_VERSION_KEY))
    client.publish(SETTINGS_INVALIDATE_CHANNEL, str(version))
    return version


def get_redis_settings_version() -> int:
    raw = _get_redis().get(SETTINGS_VERSION_KEY)
    if raw is None:
        return 0
    return int(raw)


async def load_into_settings(session: AsyncSession) -> None:
    """Read global app_settings and overwrite the in-memory settings singleton."""
    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == GLOBAL_SCOPE,
            AppSetting.user_id.is_(None),
            AppSetting.key.in_(MANAGED_KEYS),
        )
    )
    rows = result.scalars().all()
    for row in rows:
        if row.key == "embedding_dimensions":
            continue
        _apply_to_settings(
            row.key,
            _coerce_value(row.key, row.value, clamp_numbers=True),
        )


async def seed_from_env_if_empty(session: AsyncSession) -> None:
    """Populate app_settings from current .env-backed settings when table is empty."""
    count = await session.scalar(
        select(func.count()).select_from(AppSetting).where(AppSetting.scope == GLOBAL_SCOPE)
    )
    if count and count > 0:
        return

    now = datetime.now(timezone.utc)
    for field in MANAGED_SETTINGS:
        if field.read_only:
            continue
        raw = getattr(settings, field.key, None)
        session.add(
            AppSetting(
                scope=GLOBAL_SCOPE,
                user_id=None,
                key=field.key,
                value=_serialize_value(raw),
                is_secret=field.is_secret,
                updated_at=now,
            )
        )
    await session.commit()
    logger.info("Seeded %s app_settings rows from environment", len(EDITABLE_KEYS))


async def seed_missing_settings(session: AsyncSession) -> int:
    """Insert app_settings rows for new keys not yet present (e.g. after Entrega A.2)."""
    result = await session.execute(
        select(AppSetting.key).where(
            AppSetting.scope == GLOBAL_SCOPE,
            AppSetting.user_id.is_(None),
        )
    )
    existing = {row[0] for row in result.all()}
    missing = [f for f in MANAGED_SETTINGS if not f.read_only and f.key not in existing]
    if not missing:
        return 0

    now = datetime.now(timezone.utc)
    for field in missing:
        raw = getattr(settings, field.key, None)
        session.add(
            AppSetting(
                scope=GLOBAL_SCOPE,
                user_id=None,
                key=field.key,
                value=_serialize_value(raw),
                is_secret=field.is_secret,
                updated_at=now,
            )
        )
    await session.commit()
    logger.info("Seeded %s missing app_settings keys", len(missing))
    return len(missing)


async def get_effective_settings(session: AsyncSession) -> dict[str, Any]:
    """Return managed keys with secrets masked for API responses."""
    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == GLOBAL_SCOPE,
            AppSetting.user_id.is_(None),
            AppSetting.key.in_(MANAGED_KEYS),
        )
    )
    db_values = {row.key: row.value for row in result.scalars().all()}
    effective: dict[str, Any] = {}

    for field in MANAGED_SETTINGS:
        if field.read_only:
            effective[field.key] = getattr(settings, field.key, None)
            continue
        raw = db_values.get(field.key)
        if raw is None:
            effective[field.key] = getattr(settings, field.key, None)
            continue
        if field.is_secret:
            effective[field.key] = mask_secret(raw)
        else:
            effective[field.key] = _coerce_value(
                field.key, raw, clamp_numbers=True
            )

    return effective


def _serialize_managed_value(key: str, value: Any) -> str | None:
    """Validate and serialize a managed key (including read-only keys for internal writes)."""
    if key not in MANAGED_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown setting key: {key}",
        )
    schema = SCHEMA_BY_KEY[key]
    if value is None:
        return None
    str_value = str(value).strip()

    if schema.field_type == "enum" and str_value not in schema.options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid value for {key}. Allowed: {', '.join(schema.options)}",
        )

    if schema.field_type == "number":
        try:
            numeric = _coerce_number(key, str_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Valor numérico inválido para {key}",
            ) from exc
        if schema.min_value is not None and numeric < schema.min_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} deve ser >= {schema.min_value}",
            )
        if schema.max_value is not None and numeric > schema.max_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} deve ser <= {schema.max_value}",
            )
        return _serialize_value(numeric)

    if schema.field_type == "textarea":
        if len(str_value) > AGENT_SYSTEM_PROMPT_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{key} excede {AGENT_SYSTEM_PROMPT_MAX_LENGTH} caracteres "
                    f"({len(str_value)} informados)"
                ),
            )
        return str_value

    return str_value if str_value else None


def _validate_change(key: str, value: Any) -> str | None:
    if key not in EDITABLE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Setting '{key}' is not editable",
        )
    return _serialize_managed_value(key, value)


async def set_setting_internal(
    session: AsyncSession,
    key: str,
    value: Any,
) -> int:
    """
    Persist one managed setting without the public edit whitelist (system flows only).

    Upserts app_settings, applies to the settings singleton, commits, and bumps Redis
    settings_version so workers reload.
    """
    schema = SCHEMA_BY_KEY[key]
    serialized = _serialize_managed_value(key, value)

    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == GLOBAL_SCOPE,
            AppSetting.user_id.is_(None),
            AppSetting.key == key,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        row = AppSetting(
            scope=GLOBAL_SCOPE,
            user_id=None,
            key=key,
            is_secret=schema.is_secret,
        )
        session.add(row)

    row.value = serialized
    row.is_secret = schema.is_secret
    row.updated_at = now
    coerced = _coerce_value(key, serialized) if serialized is not None else None
    _apply_to_settings(key, coerced)

    await session.commit()
    version = _publish_invalidation()
    logger.info("Internal setting %s updated (redis version=%s)", key, version)

    from app.services.settings_sync import mark_local_version

    mark_local_version(version)
    return version


def _should_skip_secret_update(key: str, new_value: Any, current_db: str | None) -> bool:
    if new_value is None:
        return True
    submitted = str(new_value).strip()
    if not submitted or submitted == SECRET_MASK:
        return True
    if current_db and submitted == mask_secret(current_db):
        return True
    return False


async def update_settings(session: AsyncSession, changes: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist, apply in-place, and notify other processes via Redis."""
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No settings provided",
        )

    unknown = set(changes) - EDITABLE_KEYS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or read-only keys: {', '.join(sorted(unknown))}",
        )

    result = await session.execute(
        select(AppSetting).where(
            AppSetting.scope == GLOBAL_SCOPE,
            AppSetting.user_id.is_(None),
            AppSetting.key.in_(list(changes.keys())),
        )
    )
    existing = {row.key: row for row in result.scalars().all()}
    now = datetime.now(timezone.utc)

    for key, value in changes.items():
        schema = SCHEMA_BY_KEY[key]
        row = existing.get(key)

        if schema.is_secret and _should_skip_secret_update(
            key, value, row.value if row else None
        ):
            continue

        serialized = _validate_change(key, value)

        if row is None:
            row = AppSetting(
                scope=GLOBAL_SCOPE,
                user_id=None,
                key=key,
                is_secret=schema.is_secret,
            )
            session.add(row)
            existing[key] = row

        row.value = serialized
        row.is_secret = schema.is_secret
        row.updated_at = now
        coerced = (
            _coerce_value(key, serialized)
            if serialized is not None
            else None
        )
        _apply_to_settings(key, coerced)

    await session.commit()
    version = _publish_invalidation()
    logger.info("Settings updated (redis version=%s)", version)

    from app.services.settings_sync import mark_local_version

    mark_local_version(version)

    return await get_effective_settings(session)


def build_settings_response_payload(effective: dict[str, Any]) -> dict[str, Any]:
    """Group effective values with schema metadata for the frontend."""
    categories_order: list[SettingCategory] = [
        "llm",
        "agent",
        "stt",
        "tts",
        "avatar",
        "system",
    ]
    categories: list[dict[str, Any]] = []

    for category in categories_order:
        fields_meta = [f for f in MANAGED_SETTINGS if f.category == category]
        if not fields_meta:
            continue
        fields: list[dict[str, Any]] = []
        for meta in fields_meta:
            fields.append(
                {
                    "key": meta.key,
                    "label": meta.label,
                    "type": meta.field_type,
                    "options": list(meta.options) if meta.options else None,
                    "is_secret": meta.is_secret,
                    "read_only": meta.read_only,
                    "value": effective.get(meta.key),
                    "min": meta.min_value,
                    "max": meta.max_value,
                    "step": meta.step,
                    "max_length": meta.max_length,
                    "default_value": meta.default_value,
                }
            )
        categories.append(
            {
                "id": category,
                "label": CATEGORY_LABELS[category],
                "fields": fields,
            }
        )

    runtime = {
        meta.key: getattr(settings, meta.key, None)
        for meta in MANAGED_SETTINGS
        if meta.key in EDITABLE_KEYS or meta.read_only
    }
    for key, val in list(runtime.items()):
        schema = SCHEMA_BY_KEY.get(key)
        if schema and schema.is_secret and val:
            runtime[key] = mask_secret(str(val))

    return {
        "categories": categories,
        "settings_version": get_redis_settings_version(),
        "runtime": runtime,
    }
