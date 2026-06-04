"""Database seed data for local development."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.agent import Agent, AgentMode
from app.models.channel import Channel, ChannelType
from app.models.user import User

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@admin.com"
DEFAULT_ADMIN_PASSWORD = "admin"
DEFAULT_ADMIN_NAME = "Admin"

SEED_CHANNEL_NAMES = (
    "WhatsApp_Agent",
    "Telegram_Agent",
    "Voice_Agent",
    "Video_Agent",
)

SEED_AGENT_NAMES = (
    "Agente_Ativo",
    "Agente_Receptivo",
)

AGENT_ATIVO_DESCRIPTION = (
    "Agente de prospecção ativa. Inicia o contato com os leads de forma proativa "
    "pelos canais habilitados na campanha (WhatsApp, Telegram, voz ou vídeo), "
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


def _video_credentials() -> dict[str, Any]:
    # avatar_url é para D-ID (URL pública). O stack padrão usa SadTalker com
    # avatar_default_image local em avatars_root — não há env para avatar_url.
    return {
        "avatar_url": "",
        "did_api_key": settings.did_api_key or "",
    }


def _seed_channel_specs() -> list[tuple[str, ChannelType, dict[str, Any], bool]]:
    whatsapp_creds = _whatsapp_credentials()
    telegram_creds = _telegram_credentials()
    voice_creds = _voice_credentials()
    video_creds = _video_credentials()

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
        (
            "Video_Agent",
            ChannelType.VIDEO,
            video_creds,
            True,
        ),
    ]


async def seed_default_channels(db: AsyncSession) -> None:
    """Cria os 4 canais padrão do admin a partir do .env (idempotente por nome)."""
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


async def ensure_seed_flags(db: AsyncSession) -> None:
    """Garante is_system=true nos canais e agentes seed (idempotente por nome)."""
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

        if updated:
            await db.commit()
            logger.info(
                "ensure_seed_flags: %d registro(s) seed marcado(s) como is_system",
                updated,
            )
    except Exception:
        await db.rollback()
        logger.exception("ensure_seed_flags falhou; startup continua")
