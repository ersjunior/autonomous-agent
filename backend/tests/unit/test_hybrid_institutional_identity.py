"""Unit tests — identidade híbrida workspace + agente (fase 2a)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.identity import (
    format_institutional_identity_block,
    merge_institutional_identity,
    resolve_identity_config,
)
from agents.workers.response_agent import build_response_messages
from app.models.app_setting import AppSetting
from app.models.campaign import Campaign
from app.services.tenant_resolution import resolve_tenant_user_id
from app.services.user_identity import (
    INSTITUTIONAL_IDENTITY_KEY,
    USER_SCOPE,
    load_user_identity,
    save_user_identity,
)

WORKSPACE_IDENTITY = {
    "company_name": "WorkspaceCo",
    "display_name": "Workspace Educação",
    "tone": "formal",
    "business_context": "Contexto do workspace.",
}

AGENT_IDENTITY = {
    "tone": "descontraído",
    "greeting_hint": "Diga olá com energia.",
}


class TestMergeInstitutionalIdentity:
    def test_agent_overrides_workspace_field(self) -> None:
        merged = merge_institutional_identity(WORKSPACE_IDENTITY, AGENT_IDENTITY)
        assert merged["tone"] == "descontraído"
        assert merged["display_name"] == "Workspace Educação"
        assert merged["greeting_hint"] == "Diga olá com energia."

    def test_agent_empty_inherits_workspace(self) -> None:
        merged = merge_institutional_identity(
            WORKSPACE_IDENTITY,
            {"tone": "", "company_name": "  "},
        )
        assert merged["tone"] == "formal"
        assert merged["company_name"] == "WorkspaceCo"

    def test_both_empty_returns_empty(self) -> None:
        assert merge_institutional_identity({}, {}) == {}
        assert merge_institutional_identity(None, None) == {}

    def test_workspace_only(self) -> None:
        merged = merge_institutional_identity(WORKSPACE_IDENTITY, None)
        assert merged == WORKSPACE_IDENTITY

    def test_agent_only(self) -> None:
        merged = merge_institutional_identity(None, AGENT_IDENTITY)
        assert merged == AGENT_IDENTITY


class TestResolveIdentityConfig:
    def test_merges_into_agent_config_preserving_operational_keys(self) -> None:
        result = resolve_identity_config(
            WORKSPACE_IDENTITY,
            {"tipo": "inbound", "identity": AGENT_IDENTITY},
        )
        assert result["tipo"] == "inbound"
        assert result["identity"]["tone"] == "descontraído"
        assert result["identity"]["display_name"] == "Workspace Educação"

    def test_workspace_only_when_no_agent_identity(self) -> None:
        result = resolve_identity_config(WORKSPACE_IDENTITY, {"tipo": "inbound"})
        assert result["identity"] == WORKSPACE_IDENTITY

    def test_empty_when_neither_has_identity(self) -> None:
        result = resolve_identity_config(None, {"tipo": "inbound"})
        assert result == {"tipo": "inbound", "identity": {}}
        assert format_institutional_identity_block(result) is None


class TestResolveTenantUserId:
    @pytest.mark.asyncio
    async def test_campaign_precedence(self) -> None:
        campaign_uid = uuid.uuid4()
        agent_uid = uuid.uuid4()
        lead_uid = uuid.uuid4()
        session = AsyncMock()
        campaign = SimpleNamespace(user_id=campaign_uid)
        lead = SimpleNamespace(user_id=lead_uid, lead_base=None)
        agent = SimpleNamespace(user_id=agent_uid)

        tenant = await resolve_tenant_user_id(
            session, agent, lead=lead, campaign=campaign
        )
        assert tenant == campaign_uid
        session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_lead_campaign_via_db(self) -> None:
        campaign_uid = uuid.uuid4()
        lead_uid = uuid.uuid4()
        agent_uid = uuid.uuid4()
        campaign_id = uuid.uuid4()
        session = AsyncMock()
        session.get = AsyncMock(
            return_value=SimpleNamespace(user_id=campaign_uid)
        )
        lead = SimpleNamespace(
            user_id=lead_uid,
            lead_base=SimpleNamespace(campaign_id=campaign_id),
        )
        agent = SimpleNamespace(user_id=agent_uid)

        tenant = await resolve_tenant_user_id(session, agent, lead=lead)
        assert tenant == campaign_uid
        session.get.assert_awaited_once_with(Campaign, campaign_id)

    @pytest.mark.asyncio
    async def test_lead_without_campaign_uses_lead_user_id(self) -> None:
        lead_uid = uuid.uuid4()
        agent_uid = uuid.uuid4()
        session = AsyncMock()
        lead = SimpleNamespace(user_id=lead_uid, lead_base=None)
        agent = SimpleNamespace(user_id=agent_uid)

        tenant = await resolve_tenant_user_id(session, agent, lead=lead)
        assert tenant == lead_uid

    @pytest.mark.asyncio
    async def test_no_lead_uses_agent_user_id(self) -> None:
        agent_uid = uuid.uuid4()
        session = AsyncMock()
        agent = SimpleNamespace(user_id=agent_uid)

        tenant = await resolve_tenant_user_id(session, agent)
        assert tenant == agent_uid


class TestUserIdentityStorage:
    @pytest.mark.asyncio
    async def test_load_user_identity_returns_none_when_missing(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        loaded = await load_user_identity(session, uuid.uuid4())
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_user_identity_parses_json(self) -> None:
        session = AsyncMock()
        row = AppSetting(
            scope=USER_SCOPE,
            user_id=uuid.uuid4(),
            key=INSTITUTIONAL_IDENTITY_KEY,
            value=json.dumps(WORKSPACE_IDENTITY),
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)

        loaded = await load_user_identity(session, row.user_id)
        assert loaded == WORKSPACE_IDENTITY

    @pytest.mark.asyncio
    async def test_save_user_identity_upsert_insert(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()  # AsyncSession.add é síncrono — não usar AsyncMock
        user_id = uuid.uuid4()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        await save_user_identity(session, user_id, WORKSPACE_IDENTITY)
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.scope == USER_SCOPE
        assert added.user_id == user_id
        assert added.key == INSTITUTIONAL_IDENTITY_KEY
        assert json.loads(added.value)["display_name"] == "Workspace Educação"


class TestHybridPromptFlow:
    def test_workspace_only_produces_identity_block(self) -> None:
        config = resolve_identity_config(WORKSPACE_IDENTITY, {"tipo": "inbound"})
        block = format_institutional_identity_block(config)
        assert block is not None
        assert "Workspace Educação" in block

    def test_merged_workspace_and_agent_in_build_response_messages(self) -> None:
        config = resolve_identity_config(
            WORKSPACE_IDENTITY,
            {"tipo": "inbound", "identity": AGENT_IDENTITY},
        )
        messages = build_response_messages(
            "Olá",
            "greeting",
            {},
            [],
            "telegram",
            agent_config=config,
        )
        identity_msgs = [
            m["content"]
            for m in messages
            if m["role"] == "system" and "Identidade institucional" in m["content"]
        ]
        assert len(identity_msgs) == 1
        assert "descontraído" in identity_msgs[0]
        assert "Workspace Educação" in identity_msgs[0]

    def test_no_identity_neutral(self) -> None:
        config = resolve_identity_config(None, {"tipo": "inbound"})
        messages = build_response_messages(
            "Olá",
            "greeting",
            {},
            [],
            "telegram",
            agent_config=config,
        )
        assert not any(
            "Identidade institucional" in m.get("content", "")
            for m in messages
            if m["role"] == "system"
        )

    def test_agent_only_phase1_unchanged(self) -> None:
        agent_only = {
            "tipo": "inbound",
            "identity": {"company_name": "Solo Agent"},
        }
        config = resolve_identity_config(None, agent_only)
        block = format_institutional_identity_block(config)
        assert block is not None
        assert "Solo Agent" in block
