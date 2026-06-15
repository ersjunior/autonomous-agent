"""Channel CRUD and webhook API routes."""

import logging
import re
import uuid
import xml.sax.saxutils
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.channels.whatsapp.handler import WhatsAppHandler
from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.config import DEFAULT_VOICE_INBOUND_GREETING, settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.channel import Channel
from app.models.user import User
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate

router = APIRouter(prefix="/channels", tags=["channels"])
whatsapp = WhatsAppHandler()
logger = logging.getLogger(__name__)

UUID_MP3_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.mp3$",
    re.IGNORECASE,
)

VOICE_INBOUND_RECORD_CALLBACK_PATH = (
    "/api/v1/channels/webhooks/voice/inbound/record-callback"
)
VOICE_INBOUND_STATUS_CALLBACK_PATH = (
    "/api/v1/channels/webhooks/voice/inbound/status"
)

VOICE_MIN_RECORDING_DURATION_SEC = 1.0
VOICE_ERROR_MESSAGE = "Desculpe, tive um problema. Vamos tentar de novo."

VOICE_TERMINAL_CALL_STATUSES = frozenset(
    {"completed", "busy", "no-answer", "failed", "canceled"}
)


def _build_voice_outbound_say_twiml(text: str) -> str:
    """TwiML fallback com <Say> (voz Twilio Polly)."""
    spoken = xml.sax.saxutils.escape((text or "").strip() or " ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Say language="pt-BR" voice="Polly.Camila">{spoken}</Say>\n'
        "</Response>"
    )


def _build_voice_outbound_play_twiml(filename: str) -> str:
    """TwiML fase 2 (b): <Play> com MP3 Coqui servido pelo backend."""
    if not UUID_MP3_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid audio filename")

    base = settings.require_public_base_url()
    play_url = xml.sax.saxutils.escape(
        f"{base}/api/v1/channels/webhooks/voice/audio/{filename}"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"  <Play>{play_url}</Play>\n"
        "</Response>"
    )


def _voice_record_block_xml(*, record_timeout_sec: int | None = None) -> str:
    base = settings.require_public_base_url()
    record_action = xml.sax.saxutils.escape(
        f"{base}{VOICE_INBOUND_RECORD_CALLBACK_PATH}"
    )
    timeout = (
        record_timeout_sec
        if record_timeout_sec is not None
        else settings.voice_silence_warning_seconds
    )
    return (
        f'  <Record action="{record_action}" method="POST" maxLength="30" '
        f'timeout="{timeout}" playBeep="false" trim="trim-silence" />\n'
    )


def _build_voice_hangup_twiml(
    play_filename_or_text: str,
    *,
    is_fallback: bool,
) -> str:
    """TwiML de despedida + encerramento da chamada."""
    if is_fallback:
        spoken = xml.sax.saxutils.escape(
            (play_filename_or_text or "").strip() or " "
        )
        speech_block = (
            f'  <Say language="pt-BR" voice="Polly.Camila">{spoken}</Say>\n'
        )
    else:
        if not UUID_MP3_PATTERN.match(play_filename_or_text):
            raise HTTPException(status_code=400, detail="Invalid audio filename")
        base = settings.require_public_base_url()
        play_url = xml.sax.saxutils.escape(
            f"{base}/api/v1/channels/webhooks/voice/audio/{play_filename_or_text}"
        )
        speech_block = f"  <Play>{play_url}</Play>\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"{speech_block}"
        "  <Hangup/>\n"
        "</Response>"
    )


def _build_voice_turn_twiml(
    play_filename_or_text: str,
    *,
    is_fallback: bool,
    record_timeout_sec: int | None = None,
) -> str:
    """TwiML de um turno: fala resposta/saudação (<Play> ou <Say>) + novo <Record>."""
    if is_fallback:
        spoken = xml.sax.saxutils.escape(
            (play_filename_or_text or "").strip() or " "
        )
        speech_block = (
            f'  <Say language="pt-BR" voice="Polly.Camila">{spoken}</Say>\n'
        )
    else:
        if not UUID_MP3_PATTERN.match(play_filename_or_text):
            raise HTTPException(status_code=400, detail="Invalid audio filename")
        base = settings.require_public_base_url()
        play_url = xml.sax.saxutils.escape(
            f"{base}/api/v1/channels/webhooks/voice/audio/{play_filename_or_text}"
        )
        speech_block = f"  <Play>{play_url}</Play>\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"{speech_block}"
        f"{_voice_record_block_xml(record_timeout_sec=record_timeout_sec)}"
        "</Response>"
    )


def _build_voice_inbound_twiml(
    greeting_filename_or_text: str,
    *,
    is_fallback: bool,
) -> str:
    """TwiML inbound V1: saudação + <Record> (delega ao helper de turno)."""
    return _build_voice_turn_twiml(
        greeting_filename_or_text,
        is_fallback=is_fallback,
        record_timeout_sec=settings.voice_silence_warning_seconds,
    )


def _parse_recording_duration(raw: str) -> float:
    try:
        return float((raw or "").strip())
    except ValueError:
        return 0.0


def _twiml_response(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


def _is_voice_silence(
    recording_url: str,
    duration: float,
    transcript: str | None = None,
) -> bool:
    """Sem fala útil: URL/duração insuficiente ou STT vazio."""
    if not (recording_url or "").strip():
        return True
    if duration < VOICE_MIN_RECORDING_DURATION_SEC:
        return True
    if transcript is not None and not (transcript or "").strip():
        return True
    return False


def _register_voice_call_status_callback(call_sid: str) -> None:
    """Registra StatusCallback na chamada ativa (cliente desligou → terminal)."""
    sid = (call_sid or "").strip()
    if not sid:
        return
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.debug("Twilio não configurado; StatusCallback de voz omitido")
        return
    try:
        from twilio.rest import Client

        base = settings.require_public_base_url()
        callback_url = f"{base}{VOICE_INBOUND_STATUS_CALLBACK_PATH}"
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.calls(sid).update(
            status_callback=callback_url,
            status_callback_method="POST",
            status_callback_event=["completed"],
        )
        logger.info("Voice StatusCallback registrado call_sid=%s url=%s", sid, callback_url)
    except Exception:
        logger.warning(
            "Falha ao registrar StatusCallback para call_sid=%s",
            sid,
            exc_info=True,
        )


async def _build_spoken_twiml_with_record(
    text: str,
    *,
    record_timeout_sec: int | None = None,
) -> str:
    """TTS Coqui + <Record> ou fallback <Say> + <Record>."""
    from app.services.voice_audio import gerar_audio_chamada

    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = " "
    try:
        filename = await gerar_audio_chamada(cleaned)
        return _build_voice_turn_twiml(
            filename,
            is_fallback=False,
            record_timeout_sec=record_timeout_sec,
        )
    except Exception as exc:
        logger.warning("Coqui spoken twiml failed, fallback <Say>: %s", exc)
        return _build_voice_turn_twiml(
            cleaned,
            is_fallback=True,
            record_timeout_sec=record_timeout_sec,
        )


async def _build_voice_hangup_twiml_from_text(text: str) -> str:
    from app.services.voice_audio import gerar_audio_chamada

    cleaned = (text or "").strip() or "Até logo."
    try:
        filename = await gerar_audio_chamada(cleaned)
        return _build_voice_hangup_twiml(filename, is_fallback=False)
    except Exception as exc:
        logger.warning("Coqui hangup twiml failed, fallback <Say>: %s", exc)
        return _build_voice_hangup_twiml(cleaned, is_fallback=True)


async def _handle_voice_silence_turn(
    session: AsyncSession,
    *,
    call_sid: str,
    from_number: str,
) -> str:
    from app.core.voice_silence_text import (
        VOICE_SILENCE_CLOSE_MESSAGE,
        VOICE_SILENCE_WARNING_MESSAGE,
    )
    from app.services.voice_call_finalize import finalize_voice_call_terminal
    from app.services.voice_call_state import (
        clear_voice_call_state,
        get_silence_stage,
        set_voice_call_state,
    )

    stage = get_silence_stage(call_sid)
    if stage == 0:
        set_voice_call_state(call_sid, silence_stage=1, from_number=from_number)
        return await _build_spoken_twiml_with_record(
            VOICE_SILENCE_WARNING_MESSAGE,
            record_timeout_sec=settings.voice_silence_close_seconds,
        )

    await finalize_voice_call_terminal(
        session,
        call_sid=call_sid,
        from_number=from_number,
        origem="VOICE_SILENCE",
    )
    await session.commit()
    clear_voice_call_state(call_sid)
    return await _build_voice_hangup_twiml_from_text(VOICE_SILENCE_CLOSE_MESSAGE)


async def _run_voice_agent_turn(
    session: AsyncSession,
    *,
    from_number: str,
    transcript: str,
    call_sid: str | None = None,
) -> str:
    """Roteamento receptivo + grafo (inline, sem Celery). Retorna texto da resposta."""
    from app.services.inbound_attendance import attend_inbound_message
    from app.services.settings_sync import ensure_settings_fresh_async
    from worker.tasks.conversation_routing import resolve_inbound_agent
    from worker.tasks.lead_tracking import find_lead_by_channel_user

    await ensure_settings_fresh_async()

    user_id = (from_number or "").strip()
    if not user_id:
        raise ValueError("From vazio no callback de gravação")

    lead = await find_lead_by_channel_user(session, "voice", user_id)
    agent = await resolve_inbound_agent(session, lead, "voice", force_receptive=True)

    logger.info(
        "Voice record turn user_id=%s lead=%s agent=%s (%s)",
        user_id,
        lead.id if lead else None,
        agent.name,
        agent.mode.value,
    )

    response_text = await attend_inbound_message(
        session,
        channel="voice",
        user_id=user_id,
        message=transcript,
        agent=agent,
        lead=lead,
        bind_capacity=False,
        twilio_call_sid=call_sid,
    )
    await session.commit()
    return (response_text or "").strip()


async def _build_agent_response_twiml(response_text: str) -> str:
    from app.services.voice_audio import gerar_audio_chamada

    cleaned = (response_text or "").strip()
    if not cleaned:
        cleaned = "Desculpe, não consegui formular uma resposta."

    try:
        filename = await gerar_audio_chamada(cleaned)
        return _build_voice_turn_twiml(
            filename,
            is_fallback=False,
            record_timeout_sec=settings.voice_silence_warning_seconds,
        )
    except Exception as exc:
        logger.warning("Coqui response failed, fallback <Say>: %s", exc)
        return _build_voice_turn_twiml(
            cleaned,
            is_fallback=True,
            record_timeout_sec=settings.voice_silence_warning_seconds,
        )


async def _get_channel(
    channel_id: uuid.UUID, user: User, db: AsyncSession
) -> Channel:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    raise_if_cannot_view(channel, user, not_found_detail="Channel not found")
    return channel


@router.get("/", response_model=list[ChannelResponse])
async def list_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Channel]:
    result = await db.execute(
        select(Channel).where(or_(Channel.is_system.is_(True), Channel.user_id == user.id))
    )
    return list(result.scalars().all())


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    channel = Channel(
        user_id=user.id,
        name=payload.name,
        type=payload.type,
        credentials=payload.credentials,
        is_active=payload.is_active,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    return await _get_channel(channel_id, user, db)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Channel:
    channel = await _get_channel(channel_id, user, db)
    raise_if_cannot_edit(channel, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    channel = await _get_channel(channel_id, user, db)
    raise_if_cannot_delete(channel, user)
    await db.delete(channel)
    await db.commit()


@router.get("/webhooks/voice/audio/{filename}")
async def voice_audio_file(filename: str):
    """Serve MP3 gerado pelo worker para Twilio <Play>."""
    if not UUID_MP3_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = Path(settings.voice_audio_root) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")

    return FileResponse(path, media_type="audio/mpeg", filename=filename)


@router.get("/webhooks/voice/outbound")
@router.post("/webhooks/voice/outbound")
async def voice_outbound_webhook(
    text: str = Query("", description="Texto a ser falado na chamada (fallback <Say>)"),
):
    """TwiML fallback com voz sintética Twilio."""
    twiml = _build_voice_outbound_say_twiml(text)
    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/outbound-audio")
@router.post("/webhooks/voice/outbound-audio")
async def voice_outbound_audio_webhook(
    audio: str = Query("", description="Nome do arquivo MP3 (UUID.mp3) gerado pelo Coqui"),
):
    """TwiML principal fase 2 (b): reproduz MP3 com voz clonada Coqui."""
    twiml = _build_voice_outbound_play_twiml(audio)
    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/inbound")
@router.post("/webhooks/voice/inbound")
async def voice_inbound_webhook(
    CallSid: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    """TwiML inbound: saudação (Coqui ou Polly) + <Record> para capturar fala do cliente."""
    from app.services.settings_sync import ensure_settings_fresh_async
    from app.services.voice_audio import gerar_audio_chamada

    await ensure_settings_fresh_async()

    mode = (settings.voice_inbound_mode or "record").strip().lower()
    if mode != "record":
        logger.warning(
            "Voice inbound mode %r not implemented; only record is supported",
            mode,
        )
        twiml = _build_voice_outbound_say_twiml(
            "Este modo de atendimento por voz ainda não está disponível."
        )
        return Response(content=twiml, media_type="application/xml")

    greeting = (settings.voice_inbound_greeting or "").strip() or DEFAULT_VOICE_INBOUND_GREETING

    logger.info(
        "Voice inbound call CallSid=%s From=%s To=%s",
        CallSid or "?",
        From or "?",
        To or "?",
    )

    call_sid = (CallSid or "").strip()
    from_number = (From or "").strip()
    if call_sid and from_number:
        from app.services.voice_call_state import remember_call_from_number

        remember_call_from_number(call_sid, from_number)
    if call_sid:
        _register_voice_call_status_callback(call_sid)

    try:
        filename = await gerar_audio_chamada(greeting)
        twiml = _build_voice_inbound_twiml(filename, is_fallback=False)
    except Exception as exc:
        logger.warning(
            "Coqui greeting failed for inbound CallSid=%s, fallback <Say>: %s",
            CallSid or "?",
            exc,
        )
        twiml = _build_voice_inbound_twiml(greeting, is_fallback=True)

    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/inbound/record-callback")
@router.post("/webhooks/voice/inbound/record-callback")
async def voice_inbound_record_callback(
    db: AsyncSession = Depends(get_db),
    CallSid: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingDuration: str = Form(""),
):
    """STT → agente RECEPTIVE → TTS + novo <Record> (loop de conversa por turnos)."""
    from agents.channels.voice.tts_stt import speech_to_text
    from agents.channels.voice.twilio_voice_client import download_recording
    from app.services.voice_call_state import reset_silence_stage

    call_sid = (CallSid or "").strip()
    from_number = (From or "").strip()

    logger.info(
        "Voice inbound record-callback CallSid=%s From=%s RecordingUrl=%s duration=%s",
        call_sid or "?",
        from_number or "?",
        RecordingUrl or "?",
        RecordingDuration or "?",
    )

    try:
        recording_url = (RecordingUrl or "").strip()
        duration = _parse_recording_duration(RecordingDuration)

        if _is_voice_silence(recording_url, duration):
            twiml = await _handle_voice_silence_turn(
                db,
                call_sid=call_sid,
                from_number=from_number,
            )
            return _twiml_response(twiml)

        audio_bytes = await download_recording(recording_url)
        transcript = (
            await speech_to_text(
                audio_bytes,
                filename="audio.wav",
                content_type="audio/wav",
            )
        ).strip()

        if _is_voice_silence(recording_url, duration, transcript):
            twiml = await _handle_voice_silence_turn(
                db,
                call_sid=call_sid,
                from_number=from_number,
            )
            return _twiml_response(twiml)

        if call_sid:
            reset_silence_stage(call_sid, from_number=from_number)

        response_text = await _run_voice_agent_turn(
            db,
            from_number=from_number,
            transcript=transcript,
            call_sid=call_sid or None,
        )
        twiml = await _build_agent_response_twiml(response_text)
        return _twiml_response(twiml)

    except Exception:
        logger.exception(
            "Voice record-callback failed CallSid=%s From=%s",
            call_sid or "?",
            from_number or "?",
        )
        twiml = _build_voice_turn_twiml(
            VOICE_ERROR_MESSAGE,
            is_fallback=True,
            record_timeout_sec=settings.voice_silence_warning_seconds,
        )
        return _twiml_response(twiml)


@router.get("/webhooks/voice/inbound/status")
@router.post("/webhooks/voice/inbound/status")
async def voice_inbound_status_callback(
    db: AsyncSession = Depends(get_db),
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    From: str = Form(""),
):
    """Twilio StatusCallback — finaliza LI se o cliente desligar sem terminal."""
    from app.services.voice_call_finalize import finalize_voice_call_terminal
    from app.services.voice_call_state import clear_voice_call_state

    call_sid = (CallSid or "").strip()
    status = (CallStatus or "").strip().lower()
    from_number = (From or "").strip()

    logger.info(
        "Voice status callback CallSid=%s CallStatus=%s From=%s",
        call_sid or "?",
        status or "?",
        from_number or "?",
    )

    if status not in VOICE_TERMINAL_CALL_STATUSES:
        return Response(content="", status_code=204)

    if call_sid:
        clear_voice_call_state(call_sid)

    finalized = await finalize_voice_call_terminal(
        db,
        call_sid=call_sid or None,
        from_number=from_number or None,
        origem="VOICE_STATUS_CALLBACK",
    )
    if finalized:
        await db.commit()

    return Response(content="", status_code=204)


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    MessageSid: str = Form(""),
):
    """Inbound WhatsApp: enfileira Celery e responde TwiML vazio (resposta via API no worker)."""
    twiml = await whatsapp.handle_webhook(
        {"Body": Body, "From": From, "To": To, "MessageSid": MessageSid}
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    """
    Inbound Telegram (TELEGRAM_MODE=webhook).

    Telegram POSTa o Update JSON; processamos via Application.process_update
    (mesma lógica do polling). Em modo polling, retorna 200 sem processar.
    """
    if not settings.is_telegram_webhook_mode():
        return JSONResponse({"ok": True, "ignored": "TELEGRAM_MODE is not webhook"})

    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN not configured")

    data: dict[str, Any] = await request.json()
    update_id = data.get("update_id")
    if update_id is not None:
        from worker.tasks.inbound_handler import try_claim_inbound_dedup

        if not try_claim_inbound_dedup("telegram", str(update_id)):
            return JSONResponse({"ok": True, "deduplicated": True})

    from agents.channels.telegram.handler import process_webhook_update

    await process_webhook_update(data, settings.telegram_bot_token)
    return JSONResponse({"ok": True})
