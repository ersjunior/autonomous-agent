"""
Modo humano (B-2) — contato escalado para atendente; bot para de responder.

Chaves Redis:
  human_mode:{channel}:{user_id}           — JSON com escalated_at, human_notified, intent…
  human_mode_notified:{channel}:{user_id}  — throttle da mensagem ocasional de espera

Política:
  - Escopo por contato (channel + user_id), independente de ACTIVE/RECEPTIVE.
  - Gatilho de entrada: escalonamento no fluxo inbound (should_escalate).
  - Saída: TTL expira (volta ao bot) OU reativação manual (exit_human_mode).
  - Enquanto ativo: inbound não chama grafo/LLM; mensagem ocasional de fila humana.
  - H-1: no escalonamento, envia wa.me ao lead e notifica operador (human_notified no JSON).
  - H-2: human_assumed_at / assumed_by; assume/finalize/devolver; sweep de timeouts (Celery Beat).

TTL (H-2): a chave Redis usa sempre human_handoff_finalize_ttl (janela longa). O sweep
aplica human_handoff_queue_ttl para devolver ao bot sem assumir; após assumir, o sweep
auto-finaliza com NEG:ABANDONO se passar do finalize_ttl.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import redis

from agents.channels.phone import normalize_phone_digits
from app.core.activation_defaults import MESSAGING_CHANNELS, normalize_channel_type
from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.agent import Agent
    from app.models.lead import Lead

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

HUMAN_MODE_WAIT_MESSAGE = (
    "Seu atendimento está na fila de atendimento humano, "
    "em breve um atendente prosseguirá."
)

_CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "voice": "Voz",
}

_LEAD_CONTACT_MESSAGE = (
    "Se preferir, fale diretamente com nosso atendente: https://wa.me/{digits}"
)
_TELEGRAM_LEAD_CONTACT_MESSAGE = (
    "Um atendente humano foi acionado e entrará em contato em breve. "
    "Se preferir falar agora pelo WhatsApp: https://wa.me/{digits}"
)


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _human_mode_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"human_mode:{ch}:{user_id}"


def _notify_key(channel: str, user_id: str) -> str:
    ch = normalize_channel_type(channel)
    return f"human_mode_notified:{ch}:{user_id}"


def _parse_human_mode_key(key: str) -> tuple[str, str] | None:
    prefix = "human_mode:"
    if not key.startswith(prefix):
        return None
    rest = key[len(prefix) :]
    if ":" not in rest:
        return None
    channel, user_id = rest.split(":", 1)
    return channel, user_id


def is_human_handoff_active() -> bool:
    """Handoff H-1 ativo quando habilitado e número do operador preenchido."""
    if not settings.human_handoff_enabled:
        return False
    return bool((settings.human_handoff_whatsapp or "").strip())


def resolved_queue_ttl_seconds() -> int:
    """TTL curto: fila humana sem assumir (preferir H-2; legado human_mode_ttl_seconds)."""
    return settings.human_handoff_queue_ttl_seconds


def resolved_finalize_ttl_seconds() -> int:
    """TTL longo: chave Redis e janela após assumir."""
    return settings.human_handoff_finalize_ttl_seconds


def _human_mode_payload_dict(
    *,
    intent: str | None = None,
    human_notified: bool = False,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "escalated_at": datetime.now(timezone.utc).isoformat(),
        "human_notified": human_notified,
        "human_assumed_at": None,
        "assumed_by": None,
    }
    if intent:
        data["intent"] = intent
    if owner_user_id:
        data["owner_user_id"] = str(owner_user_id)
    return data


def _write_human_mode_payload(
    channel: str,
    user_id: str,
    data: dict[str, Any],
    *,
    ttl: int | None = None,
) -> None:
    ch = normalize_channel_type(channel)
    ex = ttl if ttl is not None else resolved_finalize_ttl_seconds()
    _get_redis().set(
        _human_mode_key(ch, user_id),
        json.dumps(data, ensure_ascii=False),
        ex=ex,
    )


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def get_human_mode_payload(channel: str, user_id: str) -> dict[str, Any] | None:
    ch = normalize_channel_type(channel)
    raw = _get_redis().get(_human_mode_key(ch, user_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def is_human_notified(channel: str, user_id: str) -> bool:
    payload = get_human_mode_payload(channel, user_id)
    return bool(payload and payload.get("human_notified"))


def mark_human_notified(channel: str, user_id: str) -> None:
    """Marca human_notified=true no payload Redis (evita re-notificar o operador)."""
    ch = normalize_channel_type(channel)
    key = _human_mode_key(ch, user_id)
    client = _get_redis()
    raw = client.get(key)
    if not raw:
        return
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    data["human_notified"] = True
    ttl = client.ttl(key)
    ex = ttl if ttl and ttl > 0 else resolved_finalize_ttl_seconds()
    client.set(key, json.dumps(data, ensure_ascii=False), ex=ex)


def is_assumed(channel: str, user_id: str) -> bool:
    payload = get_human_mode_payload(channel, user_id)
    return bool(payload and payload.get("human_assumed_at"))


def assume_human_mode(
    channel: str,
    user_id: str,
    *,
    assumed_by: str | None = None,
) -> bool:
    """Operador assume o atendimento; estende TTL para finalize_ttl."""
    ch = normalize_channel_type(channel)
    if not is_in_human_mode(ch, user_id):
        return False
    data = get_human_mode_payload(ch, user_id) or _human_mode_payload_dict()
    if data.get("human_assumed_at"):
        logger.info("Handoff já assumido channel=%s user=%s", ch, user_id)
        return True
    data["human_assumed_at"] = datetime.now(timezone.utc).isoformat()
    if assumed_by:
        data["assumed_by"] = assumed_by
    _write_human_mode_payload(
        ch,
        user_id,
        data,
        ttl=resolved_finalize_ttl_seconds(),
    )
    logger.info(
        "Handoff assumido channel=%s user=%s by=%s ttl=%ss",
        ch,
        user_id,
        assumed_by or "—",
        resolved_finalize_ttl_seconds(),
    )
    return True


def finalize_human_mode(channel: str, user_id: str) -> bool:
    """Encerra handoff (finalização com tabulação) — remove chaves Redis."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    removed = client.delete(_human_mode_key(ch, user_id))
    client.delete(_notify_key(ch, user_id))
    if removed:
        logger.info("Handoff finalizado channel=%s user=%s", ch, user_id)
    return bool(removed)


def enter_human_mode(
    channel: str,
    user_id: str,
    *,
    intent: str | None = None,
    human_notified: bool = False,
    owner_user_id: str | uuid.UUID | None = None,
) -> None:
    """Marca contato em modo humano com TTL de segurança."""
    ch = normalize_channel_type(channel)
    payload = _human_mode_payload_dict(
        intent=intent,
        human_notified=human_notified,
        owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
    )
    _write_human_mode_payload(ch, user_id, payload)
    logger.info(
        "Modo humano ativado channel=%s user=%s owner=%s redis_ttl=%ss queue_ttl=%ss",
        ch,
        user_id,
        owner_user_id or "—",
        resolved_finalize_ttl_seconds(),
        resolved_queue_ttl_seconds(),
    )


async def resolve_handoff_owner(
    session: AsyncSession,
    channel: str,
    contact_user_id: str,
    *,
    owner_user_id_from_payload: str | None = None,
) -> uuid.UUID | None:
    """
    Dono do handoff para isolamento de tenant.

    Usa owner_user_id do payload Redis quando presente; senão resolve-on-read via DB
    (campaign.user_id → lead.user_id → pool receptivo institucional).
    """
    if owner_user_id_from_payload:
        try:
            return uuid.UUID(str(owner_user_id_from_payload))
        except (ValueError, TypeError):
            pass

    payload = get_human_mode_payload(channel, contact_user_id)
    if payload and payload.get("owner_user_id"):
        try:
            return uuid.UUID(str(payload["owner_user_id"]))
        except (ValueError, TypeError):
            pass

    from worker.tasks.lead_tracking import find_lead_by_channel_user

    lead = await find_lead_by_channel_user(session, channel, contact_user_id)
    if lead is not None:
        if lead.lead_base is not None and lead.lead_base.campaign_id is not None:
            from app.models.campaign import Campaign

            campaign = await session.get(Campaign, lead.lead_base.campaign_id)
            if campaign is not None:
                return campaign.user_id
        return lead.user_id

    from app.services.attendance_history import get_receptive_pool_owner_id

    return await get_receptive_pool_owner_id(session)


async def resolve_handoff_owner_for_escalation(
    session: AsyncSession,
    agent: Agent,
    lead: Lead | None,
) -> str:
    """Regra de escrita: campaign.user_id → lead.user_id → agent.user_id (órfão)."""
    from app.services.tenant_resolution import resolve_tenant_user_id

    tenant_id = await resolve_tenant_user_id(session, agent, lead=lead)
    return str(tenant_id)


def _lead_display_name(lead: Lead | None, user_id: str) -> str:
    if lead is not None:
        name = (getattr(lead, "nome_cliente", None) or "").strip()
        if name:
            return name
        for phone_field in ("telefone_1", "telefone_2", "telefone_3"):
            phone = (getattr(lead, phone_field, None) or "").strip()
            if phone:
                return phone
    return user_id


def _build_operator_notification(
    *,
    channel: str,
    lead_label: str,
    intent: str,
    message_excerpt: str,
    timestamp: datetime,
) -> str:
    ch_label = _CHANNEL_LABELS.get(normalize_channel_type(channel), channel)
    excerpt = (message_excerpt or "").strip()
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."
    ts = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "🔔 Novo atendimento humano\n"
        f"Canal: {ch_label}\n"
        f"Lead: {lead_label}\n"
        f"Motivo: {intent}\n"
        f'Mensagem: "{excerpt}"\n'
        f"Horário: {ts}\n"
        "Responda diretamente ao cliente."
    )


async def handle_escalation_handoff(
    session: AsyncSession,
    *,
    channel: str,
    user_id: str,
    lead: Lead | None,
    message: str,
    intent: str,
) -> None:
    """
    H-1: após escalonamento, envia wa.me ao lead e notifica operador no WhatsApp.

    Falha na notificação Twilio é logada e não interrompe o modo humano.
    """
    if not is_human_handoff_active():
        return
    if is_human_notified(channel, user_id):
        logger.info(
            "Handoff H-1: operador já notificado channel=%s user=%s",
            normalize_channel_type(channel),
            user_id,
        )
        return

    from worker.tasks.inbound_handler import _deliver_inbound_response

    ch = normalize_channel_type(channel)
    operator_digits = normalize_phone_digits(settings.human_handoff_whatsapp)

    if ch in MESSAGING_CHANNELS and operator_digits:
        if ch == "whatsapp":
            contact_text = _LEAD_CONTACT_MESSAGE.format(digits=operator_digits)
        elif ch == "telegram":
            contact_text = _TELEGRAM_LEAD_CONTACT_MESSAGE.format(digits=operator_digits)
        else:
            contact_text = _LEAD_CONTACT_MESSAGE.format(digits=operator_digits)
        try:
            await _deliver_inbound_response(ch, user_id, contact_text)
            logger.info(
                "Handoff H-1: contato wa.me enviado ao lead channel=%s user=%s",
                ch,
                user_id,
            )
        except Exception:
            logger.exception(
                "Handoff H-1: falha ao enviar wa.me ao lead channel=%s user=%s",
                ch,
                user_id,
            )

    if lead is None:
        from worker.tasks.lead_tracking import find_lead_by_channel_user

        lead = await find_lead_by_channel_user(session, ch, user_id)

    lead_label = _lead_display_name(lead, user_id)
    notification_body = _build_operator_notification(
        channel=ch,
        lead_label=lead_label,
        intent=intent or "other",
        message_excerpt=message,
        timestamp=datetime.now(timezone.utc),
    )

    try:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            logger.warning(
                "Handoff H-1: Twilio não configurado; notificação ao operador omitida"
            )
        elif not (settings.twilio_phone_number or "").strip():
            logger.warning(
                "Handoff H-1: TWILIO_PHONE_NUMBER vazio; notificação ao operador omitida"
            )
        else:
            from agents.channels.whatsapp.twilio_client import send_whatsapp_message

            sid = send_whatsapp_message(settings.human_handoff_whatsapp, notification_body)
            logger.info(
                "Handoff H-1: operador notificado whatsapp=%s message_sid=%s",
                settings.human_handoff_whatsapp,
                sid,
            )
    except Exception:
        logger.exception(
            "Handoff H-1: falha ao notificar operador whatsapp=%s (modo humano mantido)",
            settings.human_handoff_whatsapp,
        )

    mark_human_notified(ch, user_id)


def is_in_human_mode(channel: str, user_id: str) -> bool:
    """True enquanto a chave existir no Redis (TTL não expirou)."""
    ch = normalize_channel_type(channel)
    return bool(_get_redis().exists(_human_mode_key(ch, user_id)))


def exit_human_mode(channel: str, user_id: str) -> bool:
    """Reativação manual — remove modo humano e throttle de notificação."""
    ch = normalize_channel_type(channel)
    client = _get_redis()
    removed = client.delete(_human_mode_key(ch, user_id))
    client.delete(_notify_key(ch, user_id))
    if removed:
        logger.info("Modo humano encerrado (manual) channel=%s user=%s", ch, user_id)
    return bool(removed)


def should_send_waiting_message(channel: str, user_id: str) -> bool:
    """
    Controla frequência da mensagem ocasional.
    Retorna True se deve enviar agora; seta chave de throttle com TTL curto.
    """
    ch = normalize_channel_type(channel)
    client = _get_redis()
    nkey = _notify_key(ch, user_id)
    interval = settings.human_mode_notify_interval_seconds
    if client.exists(nkey):
        return False
    client.set(nkey, str(time.time()), ex=interval)
    return True


def get_human_mode_escalated_at(channel: str, user_id: str) -> datetime | None:
    data = get_human_mode_payload(channel, user_id)
    if not data:
        return None
    ts = data.get("escalated_at")
    if ts:
        try:
            return datetime.fromisoformat(str(ts))
        except (ValueError, TypeError):
            pass
    return None


def handle_human_mode_inbound(channel: str, user_id: str) -> tuple[bool, str | None]:
    """
    Curto-circuito do inbound enquanto em modo humano.

    Returns:
        (handled, message_to_send) — message_to_send é None se throttle ativo.
    """
    if not is_in_human_mode(channel, user_id):
        return False, None

    msg: str | None = None
    if should_send_waiting_message(channel, user_id):
        msg = HUMAN_MODE_WAIT_MESSAGE

    logger.info(
        "Modo humano: inbound curto-circuitado channel=%s user=%s notify=%s",
        normalize_channel_type(channel),
        user_id,
        msg is not None,
    )
    return True, msg


def list_active_human_mode_contacts() -> list[dict[str, Any]]:
    """Lista contatos com human_mode:* ativo (para painel)."""
    client = _get_redis()
    contacts: list[dict[str, Any]] = []
    for key in client.scan_iter("human_mode:*", count=100):
        parsed = _parse_human_mode_key(key)
        if parsed is None:
            continue
        channel, uid = parsed
        ttl = client.ttl(key)
        payload = get_human_mode_payload(channel, uid) or {}
        escalated_at = _parse_iso_datetime(payload.get("escalated_at"))
        assumed_at = _parse_iso_datetime(payload.get("human_assumed_at"))
        contacts.append(
            {
                "channel": channel,
                "user_id": uid,
                "owner_user_id": payload.get("owner_user_id"),
                "escalated_at": escalated_at.isoformat() if escalated_at else None,
                "human_assumed_at": assumed_at.isoformat() if assumed_at else None,
                "assumed_by": payload.get("assumed_by"),
                "human_notified": bool(payload.get("human_notified")),
                "intent": payload.get("intent"),
                "is_assumed": assumed_at is not None,
                "ttl_seconds": ttl if ttl >= 0 else None,
            }
        )
    contacts.sort(key=lambda c: c.get("escalated_at") or "", reverse=True)
    return contacts


async def finalize_handoff_lead(
    session: AsyncSession,
    *,
    channel: str,
    user_id: str,
    tabulacao_codigo: str,
    status_interno: str | None = None,
    origem: str = "HANDOFF_FINALIZE",
) -> bool:
    """
    H-2: finaliza handoff com tabulação escolhida e status terminal.

    Não usa maybe_apply_tabulacao_on_transition — aplica diretamente o código informado.
    """
    from app.services.tabulacao_assignment import apply_tabulacao
    from app.services.tabulacao_mapping import status_from_tabulacao_codigo
    from worker.tasks.lead_tracking import find_lead_by_channel_user, upsert_lead_interaction

    ch = normalize_channel_type(channel)
    lead = await find_lead_by_channel_user(session, ch, user_id)
    if lead is None or lead.lead_base is None:
        logger.warning(
            "finalize_handoff_lead: lead não encontrado channel=%s user=%s",
            ch,
            user_id,
        )
        finalize_human_mode(ch, user_id)
        return False

    status = (status_interno or status_from_tabulacao_codigo(tabulacao_codigo)).lower()
    campaign_id = lead.lead_base.campaign_id

    record = await upsert_lead_interaction(
        session,
        lead.id,
        campaign_id,
        ch,
        status=status,
    )
    await apply_tabulacao(
        session,
        record,
        status_interno=status,
        channel=ch,
        origem=origem,
        tabulacao_codigo=tabulacao_codigo,
    )
    await session.flush()
    finalize_human_mode(ch, user_id)
    logger.info(
        "Handoff finalizado lead=%s channel=%s tabulacao=%s status=%s",
        lead.id,
        ch,
        tabulacao_codigo,
        status,
    )
    return True


async def sweep_human_handoff_timeouts(session: AsyncSession) -> dict[str, int]:
    """
    Varre human_mode:* e aplica timeouts H-2.

    - Não assumido + queue_ttl → exit_human_mode (devolve ao bot)
    - Assumido + finalize_ttl → auto-finaliza NEG:ABANDONO / nao_atendido
    """
    from app.services.tabulacao_mapping import AUTO_ABANDON_TABULACAO_CODIGO

    now = datetime.now(timezone.utc)
    queue_ttl = resolved_queue_ttl_seconds()
    finalize_ttl = resolved_finalize_ttl_seconds()
    returned = 0
    auto_finalized = 0

    for row in list_active_human_mode_contacts():
        ch = row["channel"]
        uid = row["user_id"]
        payload = get_human_mode_payload(ch, uid) or {}
        escalated_at = _parse_iso_datetime(payload.get("escalated_at"))
        assumed_at = _parse_iso_datetime(payload.get("human_assumed_at"))

        if assumed_at is not None:
            elapsed = (now - assumed_at).total_seconds()
            if elapsed >= finalize_ttl:
                ok = await finalize_handoff_lead(
                    session,
                    channel=ch,
                    user_id=uid,
                    tabulacao_codigo=AUTO_ABANDON_TABULACAO_CODIGO,
                    status_interno="nao_atendido",
                    origem="HANDOFF_TIMEOUT",
                )
                if ok:
                    auto_finalized += 1
                else:
                    finalize_human_mode(ch, uid)
                    auto_finalized += 1
                logger.info(
                    "Handoff auto-finalizado (timeout assumido) channel=%s user=%s elapsed=%ss",
                    ch,
                    uid,
                    int(elapsed),
                )
            continue

        if escalated_at is None:
            continue
        elapsed = (now - escalated_at).total_seconds()
        if elapsed >= queue_ttl:
            if exit_human_mode(ch, uid):
                returned += 1
                logger.info(
                    "Handoff devolvido ao bot (queue timeout) channel=%s user=%s elapsed=%ss",
                    ch,
                    uid,
                    int(elapsed),
                )

    return {"returned_to_bot": returned, "auto_finalized": auto_finalized}
