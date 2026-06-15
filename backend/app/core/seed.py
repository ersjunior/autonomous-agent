"""Database seed data for local development."""

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.agent import Agent, AgentMode
from app.models.campaign import Campaign, CampaignChannel
from app.models.channel import Channel, ChannelType
from app.models.tabulacao import Tabulacao, TabulacaoCategoria
from app.models.user import User

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@admin.com"
DEFAULT_ADMIN_PASSWORD = "admin"
DEFAULT_ADMIN_NAME = "Admin"

SEED_CHANNEL_NAMES = (
    "WhatsApp_Agent",
    "Telegram_Agent",
    "Voice_Agent",
)

SEED_AGENT_NAMES = (
    "Agente_Ativo",
    "Agente_Receptivo",
)

SEED_CAMPAIGN_NAMES = (
    "Campanha Ativa",
    "Campanha Receptiva",
)

OBSOLETE_CAMPAIGN_NAMES = ("Validação Stop Sistema",)

SEED_CAMPAIGN_CHANNEL_TYPES = ("whatsapp", "telegram", "voice")

SEED_TABULACAO_CODIGOS = (
    "SIP:200",
    "SIP:486",
    "SIP:480",
    "SIP:487",
    "SIP:404",
    "SIP:603",
    "SIP:408",
    "SIP:484",
    "NEG:ABANDONO",
    "NEG:NUM_ERRADO",
    "NEG:AUSENTE",
    "NEG:DESLIGOU",
    "NEG:SUCESSO",
    "NEG:VENDA",
    "NEG:RECUSADO",
    "NEG:ESCALADO",
)

AGENT_ATIVO_DESCRIPTION = (
    "Agente de prospecção ativa. Inicia o contato com os leads de forma proativa "
    "pelos canais habilitados na campanha (WhatsApp, Telegram ou voz), "
    "conduz a abordagem inicial, apresenta a oferta, qualifica o interesse e dá "
    "sequência às respostas do lead enquanto a conversa que ele iniciou permanecer "
    "aberta. Atua exclusivamente em fluxos iniciados pelo sistema (outbound); "
    "não atende primeiros contatos receptivos."
)

AGENT_RECEPTIVO_DESCRIPTION = (
    "Agente de atendimento receptivo. Atende o primeiro contato espontâneo do lead "
    "e conversas sem acionamento ativo em andamento, identificando a intenção, "
    "esclarecendo dúvidas, conduzindo o atendimento com base no histórico e "
    "escalando para um atendente humano quando necessário. Atua exclusivamente em "
    "fluxos iniciados pelo lead (inbound); não realiza acionamentos ativos."
)


async def seed_default_admin(db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
    if result.scalar_one_or_none() is not None:
        return

    db.add(
        User(
            email=DEFAULT_ADMIN_EMAIL,
            hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
            full_name=DEFAULT_ADMIN_NAME,
        )
    )
    await db.commit()
    print(f"Default admin user created: {DEFAULT_ADMIN_EMAIL}")


def _voice_phone_numbers() -> list[str]:
    if not (settings.twilio_voice_number or settings.twilio_phone_number):
        return []
    try:
        return [settings.resolve_twilio_pstn_number()]
    except ValueError:
        return []


def _whatsapp_credentials() -> dict[str, Any]:
    return {
        "account_sid": settings.twilio_account_sid or "",
        "auth_token": settings.twilio_auth_token or "",
        "phone_number": settings.twilio_phone_number or "",
    }


def _whatsapp_is_active(creds: dict[str, Any]) -> bool:
    return bool(
        (creds.get("account_sid") or "").strip()
        and (creds.get("auth_token") or "").strip()
        and (creds.get("phone_number") or "").strip()
    )


def _telegram_credentials() -> dict[str, Any]:
    return {"bot_token": settings.telegram_bot_token or ""}


def _voice_credentials() -> dict[str, Any]:
    return {
        "provider": "twilio",
        "phone_numbers": _voice_phone_numbers(),
    }


def _seed_channel_specs() -> list[tuple[str, ChannelType, dict[str, Any], bool]]:
    whatsapp_creds = _whatsapp_credentials()
    telegram_creds = _telegram_credentials()
    voice_creds = _voice_credentials()

    return [
        (
            "WhatsApp_Agent",
            ChannelType.WHATSAPP,
            whatsapp_creds,
            _whatsapp_is_active(whatsapp_creds),
        ),
        (
            "Telegram_Agent",
            ChannelType.TELEGRAM,
            telegram_creds,
            bool((telegram_creds.get("bot_token") or "").strip()),
        ),
        (
            "Voice_Agent",
            ChannelType.VOICE,
            voice_creds,
            bool(voice_creds.get("phone_numbers")),
        ),
    ]


async def seed_default_channels(db: AsyncSession) -> None:
    """Cria os 3 canais padrão do admin a partir do .env (idempotente por nome)."""
    try:
        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if admin is None:
            logger.warning(
                "seed_default_channels: admin %s não encontrado; pulando seed de canais",
                DEFAULT_ADMIN_EMAIL,
            )
            return

        created = 0
        for channel_name, channel_type, credentials, is_active in _seed_channel_specs():
            existing = await db.execute(
                select(Channel).where(
                    Channel.user_id == admin.id,
                    Channel.name == channel_name,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            db.add(
                Channel(
                    user_id=admin.id,
                    name=channel_name,
                    type=channel_type,
                    credentials=credentials,
                    is_active=is_active,
                    is_system=True,
                )
            )
            created += 1

        if created:
            await db.commit()
            logger.info("seed_default_channels: %d canal(is) padrão criado(s)", created)
    except Exception:
        await db.rollback()
        logger.exception("seed_default_channels falhou; startup continua")


def _seed_agent_specs() -> list[dict]:
    return [
        {
            "name": "Agente_Ativo",
            "mode": AgentMode.ACTIVE,
            "description": AGENT_ATIVO_DESCRIPTION,
            "config": {"tipo": "outbound"},
        },
        {
            "name": "Agente_Receptivo",
            "mode": AgentMode.RECEPTIVE,
            "description": AGENT_RECEPTIVO_DESCRIPTION,
            "config": {"tipo": "inbound"},
        },
    ]


async def seed_default_agents(db: AsyncSession) -> None:
    """Cria os 2 agentes padrão do admin (idempotente por nome)."""
    try:
        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if admin is None:
            logger.warning(
                "seed_default_agents: admin %s não encontrado; pulando seed de agentes",
                DEFAULT_ADMIN_EMAIL,
            )
            return

        created = 0
        for spec in _seed_agent_specs():
            existing = await db.execute(
                select(Agent).where(
                    Agent.user_id == admin.id,
                    Agent.name == spec["name"],
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            db.add(
                Agent(
                    user_id=admin.id,
                    name=spec["name"],
                    mode=spec["mode"],
                    status="active",
                    description=spec["description"],
                    config=spec["config"],
                    is_system=True,
                )
            )
            created += 1

        if created:
            await db.commit()
            logger.info("seed_default_agents: %d agente(s) padrão criado(s)", created)
    except Exception:
        await db.rollback()
        logger.exception("seed_default_agents falhou; startup continua")


def _seed_campaign_specs() -> list[dict[str, str]]:
    return [
        {"name": "Campanha Ativa", "agent_name": "Agente_Ativo"},
        {"name": "Campanha Receptiva", "agent_name": "Agente_Receptivo"},
    ]


async def _sync_campaign_channels(
    db: AsyncSession,
    campaign: Campaign,
    channel_types: tuple[str, ...],
) -> bool:
    """Garante os canais da campanha; retorna True se houve alteração."""
    result = await db.execute(
        select(CampaignChannel.channel_type).where(
            CampaignChannel.campaign_id == campaign.id
        )
    )
    existing = {row.lower() for row in result.scalars().all()}
    desired = {ch.lower() for ch in channel_types}
    if existing == desired:
        return False

    await db.execute(delete(CampaignChannel).where(CampaignChannel.campaign_id == campaign.id))
    for channel_type in channel_types:
        db.add(CampaignChannel(campaign_id=campaign.id, channel_type=channel_type.lower()))
    return True


async def cleanup_obsolete_campaigns(db: AsyncSession) -> None:
    """Remove campanhas de validação legadas (sem dados associados esperados)."""
    try:
        removed = 0
        for name in OBSOLETE_CAMPAIGN_NAMES:
            result = await db.execute(select(Campaign).where(Campaign.name == name))
            campaign = result.scalar_one_or_none()
            if campaign is None:
                continue
            await db.delete(campaign)
            removed += 1

        if removed:
            await db.commit()
            logger.info("cleanup_obsolete_campaigns: %d campanha(s) obsoleta(s) removida(s)", removed)
    except Exception:
        await db.rollback()
        logger.exception("cleanup_obsolete_campaigns falhou; startup continua")


async def seed_default_campaigns(db: AsyncSession) -> None:
    """Cria ou atualiza campanhas padrão do admin (idempotente por nome)."""
    try:
        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if admin is None:
            logger.warning(
                "seed_default_campaigns: admin %s não encontrado; pulando seed de campanhas",
                DEFAULT_ADMIN_EMAIL,
            )
            return

        created = 0
        updated = 0
        for spec in _seed_campaign_specs():
            agent_row = await db.execute(
                select(Agent).where(
                    Agent.user_id == admin.id,
                    Agent.name == spec["agent_name"],
                )
            )
            agent = agent_row.scalar_one_or_none()
            if agent is None:
                logger.warning(
                    "seed_default_campaigns: agente %s não encontrado; pulando %s",
                    spec["agent_name"],
                    spec["name"],
                )
                continue

            existing = await db.execute(
                select(Campaign).where(
                    Campaign.user_id == admin.id,
                    Campaign.name == spec["name"],
                )
            )
            campaign = existing.scalar_one_or_none()
            if campaign is None:
                campaign = Campaign(
                    user_id=admin.id,
                    agent_id=agent.id,
                    name=spec["name"],
                    status="active",
                    is_system=True,
                )
                db.add(campaign)
                await db.flush()
                await _sync_campaign_channels(db, campaign, SEED_CAMPAIGN_CHANNEL_TYPES)
                created += 1
                continue

            changed = False
            if not campaign.is_system:
                campaign.is_system = True
                changed = True
            if campaign.agent_id != agent.id:
                campaign.agent_id = agent.id
                changed = True
            if campaign.status != "active":
                campaign.status = "active"
                changed = True
            if await _sync_campaign_channels(db, campaign, SEED_CAMPAIGN_CHANNEL_TYPES):
                changed = True
            if changed:
                updated += 1

        if created or updated:
            await db.commit()
            logger.info(
                "seed_default_campaigns: %d criada(s), %d atualizada(s)",
                created,
                updated,
            )
    except Exception:
        await db.rollback()
        logger.exception("seed_default_campaigns falhou; startup continua")


def _seed_tabulacao_specs() -> list[dict]:
    return [
        # SIP — telefonia
        {"codigo": "SIP:200", "nome": "Atendida", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": False},
        {"codigo": "SIP:486", "nome": "Ocupado", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:480", "nome": "Indisponível", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:487", "nome": "Cancelada", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:404", "nome": "Número inexistente", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:603", "nome": "Recusada", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:408", "nome": "Sem resposta/Timeout", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        {"codigo": "SIP:484", "nome": "Número incompleto", "categoria": TabulacaoCategoria.TELEFONIA, "is_terminal": True},
        # Negócio
        {"codigo": "NEG:ABANDONO", "nome": "Abandono", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {"codigo": "NEG:NUM_ERRADO", "nome": "Número Errado", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {"codigo": "NEG:AUSENTE", "nome": "Cliente Ausente", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {"codigo": "NEG:DESLIGOU", "nome": "Desligou", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {"codigo": "NEG:SUCESSO", "nome": "Sucesso", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {"codigo": "NEG:VENDA", "nome": "Venda", "categoria": TabulacaoCategoria.NEGOCIO, "is_terminal": True},
        {
            "codigo": "NEG:RECUSADO",
            "nome": "Recusado",
            "categoria": TabulacaoCategoria.NEGOCIO,
            "is_terminal": True,
            "descricao": "Cliente recusou explicitamente a oferta (intent cancel).",
        },
        {
            "codigo": "NEG:ESCALADO",
            "nome": "Escalado para humano",
            "categoria": TabulacaoCategoria.NEGOCIO,
            "is_terminal": True,
            "descricao": (
                "Atendimento do bot encerrado por escalonamento para humano "
                "(pedido explícito, baixa confiança ou reclamação grave). "
                "is_terminal=true do ponto de vista do bot; o lead segue com atendente."
            ),
        },
    ]


async def seed_default_tabulacoes(db: AsyncSession) -> None:
    """Cria catálogo SIP + status de negócio do admin (idempotente por codigo entre is_system)."""
    try:
        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if admin is None:
            logger.warning(
                "seed_default_tabulacoes: admin %s não encontrado; pulando seed de tabulações",
                DEFAULT_ADMIN_EMAIL,
            )
            return

        created = 0
        for spec in _seed_tabulacao_specs():
            existing = await db.execute(
                select(Tabulacao).where(
                    Tabulacao.is_system.is_(True),
                    Tabulacao.codigo == spec["codigo"],
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            db.add(
                Tabulacao(
                    user_id=admin.id,
                    nome=spec["nome"],
                    codigo=spec["codigo"],
                    categoria=spec["categoria"].value,
                    is_terminal=spec["is_terminal"],
                    is_system=True,
                    descricao=spec.get("descricao"),
                )
            )
            created += 1

        if created:
            await db.commit()
            logger.info("seed_default_tabulacoes: %d tabulação(ões) padrão criada(s)", created)
    except Exception:
        await db.rollback()
        logger.exception("seed_default_tabulacoes falhou; startup continua")


async def ensure_seed_flags(db: AsyncSession) -> None:
    """Garante is_system=true nos canais, agentes, campanhas e tabulações seed (idempotente)."""
    try:
        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        admin = result.scalar_one_or_none()
        if admin is None:
            return

        updated = 0
        for channel_name in SEED_CHANNEL_NAMES:
            row = await db.execute(
                select(Channel).where(
                    Channel.user_id == admin.id,
                    Channel.name == channel_name,
                )
            )
            channel = row.scalar_one_or_none()
            if channel is None or channel.is_system:
                continue
            channel.is_system = True
            updated += 1

        for agent_name in SEED_AGENT_NAMES:
            row = await db.execute(
                select(Agent).where(
                    Agent.user_id == admin.id,
                    Agent.name == agent_name,
                )
            )
            agent = row.scalar_one_or_none()
            if agent is None or agent.is_system:
                continue
            agent.is_system = True
            updated += 1

        for campaign_name in SEED_CAMPAIGN_NAMES:
            row = await db.execute(
                select(Campaign).where(
                    Campaign.user_id == admin.id,
                    Campaign.name == campaign_name,
                )
            )
            campaign = row.scalar_one_or_none()
            if campaign is None or campaign.is_system:
                continue
            campaign.is_system = True
            updated += 1

        for codigo in SEED_TABULACAO_CODIGOS:
            row = await db.execute(
                select(Tabulacao).where(
                    Tabulacao.user_id == admin.id,
                    Tabulacao.codigo == codigo,
                )
            )
            tabulacao = row.scalar_one_or_none()
            if tabulacao is None or tabulacao.is_system:
                continue
            tabulacao.is_system = True
            updated += 1

        if updated:
            await db.commit()
            logger.info(
                "ensure_seed_flags: %d registro(s) seed marcado(s) como is_system",
                updated,
            )
    except Exception:
        await db.rollback()
        logger.exception("ensure_seed_flags falhou; startup continua")
