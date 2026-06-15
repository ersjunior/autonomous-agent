"""Central ownership and system-record authorization helpers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status

from app.models.lead_base import LeadBase, LeadBaseSource
from app.models.user import User

SYSTEM_RECORD_EDIT_DETAIL = "Registro padrão do sistema não pode ser editado"
SYSTEM_RECORD_DELETE_DETAIL = "Registro padrão do sistema não pode ser excluído"
IMPORT_LEAD_EDIT_DETAIL = "Leads de base importada são somente leitura"
IMPORT_LEAD_DELETE_DETAIL = "Leads de base importada são somente leitura"


def _is_campaign(record: Any) -> bool:
    """Campaign is the only model where is_system blocks delete but not edit."""
    from app.models.campaign import Campaign

    return isinstance(record, Campaign)


def record_owner_id(record: Any) -> uuid.UUID:
    """Resolve owner user_id for Agent, Channel, Tabulacao, Campaign, Lead, or LeadBase."""
    if isinstance(record, LeadBase):
        campaign = record.campaign
        if campaign is None:
            raise ValueError("LeadBase.campaign must be loaded for owner resolution")
        return campaign.user_id
    return record.user_id


def can_view(record: Any, user: User) -> bool:
    """System records are visible to everyone; otherwise only the owner."""
    if bool(getattr(record, "is_system", False)):
        return True
    if isinstance(record, LeadBase):
        campaign = record.campaign
        if campaign is not None and bool(getattr(campaign, "is_system", False)):
            return True
    return record_owner_id(record) == user.id


def can_edit(record: Any, user: User) -> bool:
    """System records are never editable except Campaign (owner may edit)."""
    if _is_campaign(record):
        return record_owner_id(record) == user.id
    return not getattr(record, "is_system", False) and record_owner_id(record) == user.id


def can_delete(record: Any, user: User) -> bool:
    """System campaigns cannot be deleted; other system records follow can_edit."""
    if _is_campaign(record) and getattr(record, "is_system", False):
        return False
    return can_edit(record, user)


def is_lead_from_import(lead: Any) -> bool:
    """Lead is read-only when its base was created via CSV import."""
    lead_base = lead.lead_base
    if lead_base is None:
        return False
    return lead_base.source == LeadBaseSource.IMPORT


def can_edit_lead(lead: Any, user: User) -> bool:
    return can_edit(lead, user) and not is_lead_from_import(lead)


def can_delete_lead(lead: Any, user: User) -> bool:
    return can_delete(lead, user) and not is_lead_from_import(lead)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def raise_if_cannot_view(record: Any, user: User, *, not_found_detail: str = "Not found") -> None:
    if not can_view(record, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)


def raise_if_cannot_edit(record: Any, user: User) -> None:
    # Campanhas is_system: editáveis pelo dono (start/stop, nome, canais, bases).
    if _is_campaign(record):
        if record_owner_id(record) != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return
    if getattr(record, "is_system", False):
        raise _forbidden(SYSTEM_RECORD_EDIT_DETAIL)
    if record_owner_id(record) != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def raise_if_cannot_delete(record: Any, user: User) -> None:
    if getattr(record, "is_system", False):
        raise _forbidden(SYSTEM_RECORD_DELETE_DETAIL)
    if record_owner_id(record) != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def raise_if_cannot_edit_lead(lead: Any, user: User) -> None:
    if getattr(lead, "is_system", False):
        raise _forbidden(SYSTEM_RECORD_EDIT_DETAIL)
    if lead.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if is_lead_from_import(lead):
        raise _forbidden(IMPORT_LEAD_EDIT_DETAIL)


def raise_if_cannot_delete_lead(lead: Any, user: User) -> None:
    if getattr(lead, "is_system", False):
        raise _forbidden(SYSTEM_RECORD_DELETE_DETAIL)
    if lead.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if is_lead_from_import(lead):
        raise _forbidden(IMPORT_LEAD_DELETE_DETAIL)
