"""Pydantic schemas for workspace institutional identity."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from agents.identity import IDENTITY_FIELD_KEYS


class InstitutionalIdentityResponse(BaseModel):
    company_name: str | None = None
    display_name: str | None = None
    tone: str | None = None
    business_context: str | None = None
    greeting_hint: str | None = None


class InstitutionalIdentityUpdate(BaseModel):
    company_name: str | None = None
    display_name: str | None = None
    tone: str | None = None
    business_context: str | None = None
    greeting_hint: str | None = None

    @field_validator(*IDENTITY_FIELD_KEYS, mode="before")
    @classmethod
    def empty_str_to_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        return str(value).strip() or None

    def to_storage_dict(self) -> dict[str, str]:
        """Campos não vazios para persistência (merge campo-a-campo no storage)."""
        result: dict[str, str] = {}
        for key in IDENTITY_FIELD_KEYS:
            raw = getattr(self, key)
            if raw is not None:
                result[key] = raw
        return result


def identity_dict_to_response(data: dict[str, str] | None) -> InstitutionalIdentityResponse:
    if not data:
        return InstitutionalIdentityResponse()
    return InstitutionalIdentityResponse(
        **{key: data.get(key) for key in IDENTITY_FIELD_KEYS}
    )
