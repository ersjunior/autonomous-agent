"""Inbound message tasks — fila Celery unificada (R-A.0 + R-A).

Fluxo inbound (WhatsApp / Telegram):
  1. Canal enfileira ``process_inbound_message.delay(channel, user_id, text)``
  2. Worker: lead → ``resolve_inbound_agent``
  3a. ACTIVE (conversa ativa): atendimento imediato (sem fila receptiva)
  3b. RECEPTIVE: janela → capacidade global+slot → atender OU fila + msg espera
  4. ``process_receptive_queue`` (Beat ~30s): dequeue FIFO quando houver capacidade

Redis (R-A):
  - Capacidade: ``global_capacity_usage``, ``global_capacity_holders``, ``contact_capacity:*``
  - Fila: ``receptive_queue:{channel}``, ``queue_payload:{channel}:{user}``

Dedup WhatsApp: ``inbound_dedup:whatsapp:{MessageSid}`` (NX, 24h).
"""

from __future__ import annotations

import asyncio
import logging

import redis

from app.core.database import AsyncSessionLocal, engine
from app.services.inbound_attendance import (
    attend_inbound_message,
    process_receptive_inbound,
    should_apply_receptive_queue,
)
from app.core.config import settings
from worker.celery_app import celery
from worker.tasks.conversation_routing import resolve_inbound_agent
from worker.tasks.lead_tracking import find_lead_by_channel_user

logger = logging.getLogger(__name__)

_INBOUND_DEDUP_TTL_SECONDS = 24 * 3600
_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def try_claim_inbound_dedup(channel: str, dedup_key: str | None) -> bool:
    """Marca mensagem como vista (SET NX). Retorna False se já processada."""
    key = (dedup_key or "").strip()
    if not key:
        return True
    redis_key = f"inbound_dedup:{channel.lower()}:{key}"
    return bool(
        _get_redis().set(redis_key, "1", nx=True, ex=_INBOUND_DEDUP_TTL_SECONDS)
    )


async def _deliver_inbound_response(channel: str, user_id: str, response: str) -> bool:
    """Envia resposta ao lead pelo canal (API ativa — não TwiML no webhook)."""
    text = (response or "").strip()
    if not text:
        logger.info("Inbound %s user_id=%s: resposta vazia, envio omitido", channel, user_id)
        return False

    ch = channel.lower()
    try:
        if ch == "whatsapp":
            from agents.channels.whatsapp.twilio_client import send_whatsapp_message

            if not settings.twilio_account_sid or not settings.twilio_auth_token:
                logger.warning(
                    "Twilio não configurado; resposta inbound WhatsApp não enviada (to=%s)",
                    user_id,
                )
                return False
            if not (settings.twilio_phone_number or "").strip():
                logger.warning(
                    "TWILIO_PHONE_NUMBER vazio; resposta inbound WhatsApp não enviada (to=%s)",
                    user_id,
                )
                return False
            sid = send_whatsapp_message(user_id, text)
            logger.info("WhatsApp inbound enviado to=%s message_sid=%s", user_id, sid)
            return True

        if ch == "telegram":
            from agents.channels.telegram.client import send_telegram_message

            if not settings.telegram_bot_token:
                logger.warning(
                    "TELEGRAM_BOT_TOKEN não configurado; resposta inbound Telegram não enviada (chat=%s)",
                    user_id,
                )
                return False
            await send_telegram_message(user_id, text)
            logger.info("Telegram inbound enviado chat_id=%s", user_id)
            return True

        logger.warning("Canal inbound não suportado para envio ativo: %s", channel)
        return False
    except Exception:
        logger.exception(
            "Falha ao enviar resposta inbound channel=%s user_id=%s",
            channel,
            user_id,
        )
        return False


async def _process_inbound_message(
    channel: str,
    user_id: str,
    message: str,
    message_sid: str | None = None,
) -> str:
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    async with AsyncSessionLocal() as session:
        lead = await find_lead_by_channel_user(session, channel, user_id)
        agent = await resolve_inbound_agent(session, lead, channel)

        logger.info(
            "Inbound roteado para agente %s (%s) channel=%s user_id=%s lead=%s",
            agent.name,
            agent.mode.value,
            channel,
            user_id,
            lead.id if lead else None,
        )

        if should_apply_receptive_queue(agent):
            response_text = await process_receptive_inbound(
                session,
                channel=channel,
                user_id=user_id,
                message=message,
                agent=agent,
                lead=lead,
                message_sid=message_sid,
            )
        else:
            response_text = await attend_inbound_message(
                session,
                channel=channel,
                user_id=user_id,
                message=message,
                agent=agent,
                lead=lead,
                bind_capacity=False,
                message_sid=message_sid,
            )

        await session.commit()

    return response_text


@celery.task(bind=True, max_retries=3)
def process_inbound_message(
    self,
    channel: str,
    user_id: str,
    message: str,
    message_sid: str | None = None,
) -> str:
    """Processa mensagem inbound: roteamento, fila receptiva (se aplicável), envio, tracking."""
    try:
        return _run_inbound_async(channel, user_id, message, message_sid)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc


def _run_inbound_async(
    channel: str,
    user_id: str,
    message: str,
    message_sid: str | None = None,
) -> str:
    """Executa corrotina inbound e descarta pool asyncpg (evita InterfaceError no prefork)."""

    async def _wrapper() -> str:
        from agents.orchestrator.graph import reset_worker_async_clients

        try:
            return await _process_inbound_message(channel, user_id, message, message_sid)
        finally:
            await reset_worker_async_clients()
            await engine.dispose()

    return asyncio.run(_wrapper())
