"""Channel CRUD and webhook API routes."""

import asyncio
import logging
import re
import uuid
import xml.sax.saxutils
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.channels.voice.audio_pipeline import is_voice_stream_available
from agents.channels.voice.stream_session import handle_voice_media_stream
from agents.channels.whatsapp.handler import WhatsAppHandler
from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.config import DEFAULT_VOICE_INBOUND_GREETING, settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.channel import Channel
from app.models.user import User
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate
from app.services.voice_cached_audio import (
    VOICE_WAIT_FILENAME,
    ensure_greeting_audio_filename,
    get_phrase_audio_filename,
    is_allowed_cached_audio_filename,
)
from app.services.voice_turn_state import (
    create_pending_turn,
    get_voice_turn,
    increment_turn_poll_count,
    mark_turn_consumed,
    mark_turn_error,
)

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
VOICE_INBOUND_TURN_READY_PATH = (
    "/api/v1/channels/webhooks/voice/inbound/turn-ready"
)

VOICE_TURN_TIMEOUT_MESSAGE = (
    "Desculpe, estou demorando mais que o esperado. Vamos tentar de novo."
)

VOICE_MIN_RECORDING_DURATION_SEC = 1.0
VOICE_ERROR_MESSAGE = "Desculpe, tive um problema. Vamos tentar de novo."

VOICE_TERMINAL_CALL_STATUSES = frozenset(
    {"completed", "busy", "no-answer", "failed", "canceled"}
)


def _is_served_audio_filename(filename: str) -> bool:
    return bool(
        UUID_MP3_PATTERN.match(filename)
        or is_allowed_cached_audio_filename(filename)
    )


def _voice_play_url(filename: str) -> str:
    base = settings.require_public_base_url()
    return f"{base}/api/v1/channels/webhooks/voice/audio/{filename}"


def _turn_ready_redirect_url(call_sid: str, turn_id: str) -> str:
    base = settings.require_public_base_url()
    return (
        f"{base}{VOICE_INBOUND_TURN_READY_PATH}"
        f"?call_sid={quote(call_sid)}"
        f"&turn_id={quote(turn_id)}"
    )


def _compute_wait_total_ms(turn: dict[str, Any]) -> float | None:
    """Tempo desde create_pending_turn até entrega do áudio (latência percebida)."""
    created = turn.get("created_at")
    if not created or not isinstance(created, str):
        return None
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created_dt).total_seconds() * 1000
    except (ValueError, TypeError):
        return None


def _build_voice_turn_redirect_twiml(*, call_sid: str, turn_id: str) -> str:
    """
    Resposta imediata do record-callback: Redirect direto para turn-ready.

    Sem <Play> de espera — o Twilio executa o áudio inteiro antes do Redirect,
    bloqueando o polling por vários segundos.
    """
    redirect_url = xml.sax.saxutils.escape(_turn_ready_redirect_url(call_sid, turn_id))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Redirect method="POST">{redirect_url}</Redirect>\n'
        "</Response>"
    )


def _build_voice_poll_twiml(
    *,
    call_sid: str,
    turn_id: str,
    play_wait: bool = False,
) -> str:
    """Polling pending: 1º ciclo opcional <Play> curto; depois Pause + Redirect."""
    redirect_url = xml.sax.saxutils.escape(_turn_ready_redirect_url(call_sid, turn_id))
    blocks: list[str] = []
    if play_wait:
        play_url = xml.sax.saxutils.escape(_voice_play_url(VOICE_WAIT_FILENAME))
        blocks.append(f"  <Play>{play_url}</Play>\n")
    else:
        pause_sec = max(1, int(settings.voice_turn_poll_pause_seconds))
        blocks.append(f'  <Pause length="{pause_sec}"/>\n')
    blocks.append(f'  <Redirect method="POST">{redirect_url}</Redirect>\n')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"{''.join(blocks)}"
        "</Response>"
    )


def _build_voice_turn_timeout_twiml() -> str:
    return _build_voice_turn_twiml(
        VOICE_TURN_TIMEOUT_MESSAGE,
        is_fallback=True,
    )


def _build_voice_say_only_twiml(text: str) -> str:
    """TwiML com <Say> apenas, sem <Record> (erro / modo indisponível)."""
    spoken = xml.sax.saxutils.escape((text or "").strip() or " ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Say language="pt-BR" voice="Polly.Camila">{spoken}</Say>\n'
        "</Response>"
    )


def _build_voice_connect_stream_twiml(wss_url: str) -> str:
    """TwiML inbound stream: <Connect><Stream> (Media Streams, sem Record)."""
    safe_url = xml.sax.saxutils.escape((wss_url or "").strip())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="{safe_url}" />\n'
        "  </Connect>\n"
        "</Response>"
    )


def _build_voice_outbound_say_twiml(text: str) -> str:
    """TwiML outbound fallback <Say> + <Record> (entra no loop de turnos inbound)."""
    return _build_voice_turn_twiml(text, is_fallback=True)


def _build_voice_outbound_play_twiml(filename: str) -> str:
    """TwiML outbound <Play> Coqui + <Record> (entra no loop de turnos inbound)."""
    return _build_voice_turn_twiml(filename, is_fallback=False)


def _voice_record_silence_timeout_sec(record_timeout_sec: int | None = None) -> int:
    if record_timeout_sec is not None:
        return max(1, int(record_timeout_sec))
    return max(1, int(settings.voice_record_silence_timeout_sec))


def _voice_record_block_xml(*, record_timeout_sec: int | None = None) -> str:
    base = settings.require_public_base_url()
    record_action = xml.sax.saxutils.escape(
        f"{base}{VOICE_INBOUND_RECORD_CALLBACK_PATH}"
    )
    timeout = _voice_record_silence_timeout_sec(record_timeout_sec)
    max_length = max(1, int(settings.voice_record_max_length_sec))
    return (
        f'  <Record action="{record_action}" method="POST" maxLength="{max_length}" '
        f'timeout="{timeout}" playBeep="false" trim="trim-silence" />\n'
    )


def _build_voice_record_only_twiml() -> str:
    """Reabre o microfone após silêncio parcial (sem fala do agente)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"{_voice_record_block_xml()}"
        "</Response>"
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
        if not _is_served_audio_filename(play_filename_or_text):
            raise HTTPException(status_code=400, detail="Invalid audio filename")
        play_url = xml.sax.saxutils.escape(_voice_play_url(play_filename_or_text))
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
        if not _is_served_audio_filename(play_filename_or_text):
            raise HTTPException(status_code=400, detail="Invalid audio filename")
        play_url = xml.sax.saxutils.escape(_voice_play_url(play_filename_or_text))
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
    )


def _parse_recording_duration(raw: str) -> float:
    try:
        return float((raw or "").strip())
    except ValueError:
        return 0.0


def _twiml_response(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


def _voice_silence_reason(
    recording_url: str,
    duration: float,
    transcript: str | None = None,
) -> str | None:
    """Motivo de classificação como silêncio (metadados Twilio; sem STT no callback)."""
    if not (recording_url or "").strip():
        return "empty_recording_url"
    if duration < VOICE_MIN_RECORDING_DURATION_SEC:
        return f"short_duration:{duration}"
    if transcript is not None and not (transcript or "").strip():
        return "empty_transcript"
    return None


def _is_voice_silence(
    recording_url: str,
    duration: float,
    transcript: str | None = None,
) -> bool:
    """Sem fala útil: URL/duração insuficiente ou STT vazio (quando transcript informado)."""
    return _voice_silence_reason(recording_url, duration, transcript) is not None


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


def _build_spoken_twiml_with_record(
    text: str,
    *,
    record_timeout_sec: int | None = None,
) -> str:
    """<Play> MP3 cacheado + <Record>, ou <Say> Polly se cache ausente (sem Coqui no webhook)."""
    cleaned = (text or "").strip() or " "
    filename = get_phrase_audio_filename(cleaned)
    if filename:
        return _build_voice_turn_twiml(
            filename,
            is_fallback=False,
            record_timeout_sec=record_timeout_sec,
        )
    logger.warning(
        "Phrase cache miss for spoken twiml; using Polly <Say> fallback",
    )
    return _build_voice_turn_twiml(
        cleaned,
        is_fallback=True,
        record_timeout_sec=record_timeout_sec,
    )


def _build_voice_hangup_twiml_from_text(text: str) -> str:
    """<Play> MP3 cacheado + <Hangup>, ou <Say> Polly (sem Coqui no webhook)."""
    cleaned = (text or "").strip() or "Até logo."
    filename = get_phrase_audio_filename(cleaned)
    if filename:
        return _build_voice_hangup_twiml(filename, is_fallback=False)
    logger.warning(
        "Phrase cache miss for hangup twiml; using Polly <Say> fallback",
    )
    return _build_voice_hangup_twiml(cleaned, is_fallback=True)


async def _handle_voice_silence_turn(
    *,
    call_sid: str,
    from_number: str,
) -> str:
    from app.core.voice_silence_text import (
        VOICE_SILENCE_CLOSE_MESSAGE,
        VOICE_SILENCE_WARNING_MESSAGE,
    )
    from app.core.database import AsyncSessionLocal
    from app.services.voice_call_finalize import finalize_voice_call_terminal
    from app.services.voice_call_state import (
        add_accumulated_silence,
        clear_voice_call_state,
        get_silence_stage,
        set_voice_call_state,
    )

    delta = float(settings.voice_record_silence_timeout_sec)
    accumulated = add_accumulated_silence(
        call_sid,
        delta,
        from_number=from_number,
    )
    stage = get_silence_stage(call_sid)
    logger.info(
        "Voice silence accumulated call_sid=%s stage=%s delta_sec=%s total_sec=%s",
        call_sid or "?",
        stage,
        delta,
        accumulated,
    )

    if stage == 0:
        if accumulated < settings.voice_silence_warning_seconds:
            return _build_voice_record_only_twiml()
        set_voice_call_state(
            call_sid,
            silence_stage=1,
            from_number=from_number,
            accumulated_silence_sec=0.0,
        )
        return _build_spoken_twiml_with_record(VOICE_SILENCE_WARNING_MESSAGE)

    if accumulated < settings.voice_silence_close_seconds:
        return _build_voice_record_only_twiml()

    async with AsyncSessionLocal() as session:
        await finalize_voice_call_terminal(
            session,
            call_sid=call_sid,
            from_number=from_number,
            origem="VOICE_SILENCE",
        )
        await session.commit()
    clear_voice_call_state(call_sid)
    return _build_voice_hangup_twiml_from_text(VOICE_SILENCE_CLOSE_MESSAGE)


async def _enqueue_voice_inbound_turn(
    *,
    call_sid: str,
    turn_id: str,
    recording_url: str,
    from_number: str,
    duration: float,
) -> None:
    """Redis + Celery fora do event loop (ops síncronas)."""
    from worker.tasks.voice_inbound_turn import process_voice_inbound_turn_task

    def _sync_enqueue() -> None:
        create_pending_turn(
            call_sid=call_sid,
            turn_id=turn_id,
            recording_url=recording_url,
            from_number=from_number,
        )
        process_voice_inbound_turn_task.delay(
            call_sid,
            turn_id,
            recording_url,
            from_number,
            duration,
        )

    await asyncio.to_thread(_sync_enqueue)


async def _run_voice_agent_turn(
    session: AsyncSession,
    *,
    from_number: str,
    transcript: str,
    call_sid: str | None = None,
) -> str:
    """Compat: delega ao service (worker + testes)."""
    from app.services.voice_turn_processor import run_voice_agent_turn

    return await run_voice_agent_turn(
        session,
        from_number=from_number,
        transcript=transcript,
        call_sid=call_sid,
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
    if not _is_served_audio_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = Path(settings.voice_audio_root) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")

    return FileResponse(path, media_type="audio/mpeg", filename=filename)


def _prepare_outbound_voice_call_context(
    call_sid: str,
    *,
    to_number: str = "",
) -> None:
    """Registra StatusCallback e telefone do lead quando Twilio busca TwiML outbound."""
    sid = (call_sid or "").strip()
    if not sid:
        return
    customer = (to_number or "").strip()
    if customer:
        from app.services.voice_call_state import remember_call_from_number

        remember_call_from_number(sid, customer)
    _register_voice_call_status_callback(sid)


def _resolve_voice_customer_number(
    call_sid: str,
    from_number: str,
    to_number: str,
) -> str:
    """Inbound: From=cliente. Outbound: To=cliente; Redis prevalece se já mapeado."""
    from app.services.voice_call_state import get_call_customer_number

    stored = get_call_customer_number(call_sid)
    if stored:
        return stored

    from_n = (from_number or "").strip()
    to_n = (to_number or "").strip()
    try:
        pstn = settings.resolve_twilio_pstn_number()
    except ValueError:
        pstn = ""
    if from_n and from_n != pstn:
        return from_n
    if to_n and to_n != pstn:
        return to_n
    return from_n or to_n


@router.get("/webhooks/voice/outbound")
@router.post("/webhooks/voice/outbound")
async def voice_outbound_webhook(
    text: str = Query("", description="Texto a ser falado na chamada (fallback <Say>)"),
    CallSid: str = Form(""),
    To: str = Form(""),
):
    """TwiML fallback <Say> + <Record> para mensagem ativa outbound."""
    _prepare_outbound_voice_call_context(CallSid, to_number=To)
    twiml = _build_voice_outbound_say_twiml(text)
    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/outbound-audio")
@router.post("/webhooks/voice/outbound-audio")
async def voice_outbound_audio_webhook(
    audio: str = Query("", description="Nome do arquivo MP3 (UUID.mp3) gerado pelo Coqui"),
    CallSid: str = Form(""),
    To: str = Form(""),
):
    """TwiML outbound <Play> Coqui + <Record> para mensagem ativa."""
    _prepare_outbound_voice_call_context(CallSid, to_number=To)
    twiml = _build_voice_outbound_play_twiml(audio)
    return Response(content=twiml, media_type="application/xml")


async def _voice_inbound_record_response(
    *,
    call_sid: str,
    from_number: str,
    to: str,
) -> Response:
    """TwiML inbound record: greeting + <Record> (shared by record mode and stream fallback)."""
    greeting = (settings.voice_inbound_greeting or "").strip() or DEFAULT_VOICE_INBOUND_GREETING

    logger.info(
        "Voice inbound call CallSid=%s From=%s To=%s",
        call_sid or "?",
        from_number or "?",
        to or "?",
    )

    if call_sid and from_number:
        from app.services.voice_call_state import remember_call_from_number

        remember_call_from_number(call_sid, from_number)
    if call_sid:
        _register_voice_call_status_callback(call_sid)

    try:
        filename = await ensure_greeting_audio_filename(greeting)
        twiml = _build_voice_inbound_twiml(filename, is_fallback=False)
    except Exception as exc:
        logger.warning(
            "Coqui greeting failed for inbound CallSid=%s, fallback <Say>: %s",
            call_sid or "?",
            exc,
        )
        twiml = _build_voice_inbound_twiml(greeting, is_fallback=True)

    return Response(content=twiml, media_type="application/xml")


@router.get("/webhooks/voice/inbound")
@router.post("/webhooks/voice/inbound")
async def voice_inbound_webhook(
    CallSid: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    """TwiML inbound: record (saudação + Record) ou stream (<Connect><Stream>)."""
    from app.services.settings_sync import ensure_settings_fresh_async

    await ensure_settings_fresh_async()

    mode = settings.voice_inbound_mode
    call_sid = (CallSid or "").strip()
    from_number = (From or "").strip()

    if mode == "stream":
        if not is_voice_stream_available():
            logger.warning(
                "Voice stream mode indisponível (webrtcvad ausente); degradando para record. "
                "CallSid=%s",
                call_sid or "?",
            )
            return await _voice_inbound_record_response(
                call_sid=call_sid,
                from_number=from_number,
                to=(To or "").strip(),
            )

        logger.info(
            "Voice inbound stream call CallSid=%s From=%s To=%s",
            call_sid or "?",
            from_number or "?",
            (To or "").strip() or "?",
        )
        if call_sid and from_number:
            from app.services.voice_call_state import remember_call_from_number

            remember_call_from_number(call_sid, from_number)
        if call_sid:
            _register_voice_call_status_callback(call_sid)
        try:
            wss_url = settings.voice_media_stream_wss_url()
        except ValueError as exc:
            logger.error(
                "Voice inbound stream CallSid=%s: public WSS URL unavailable: %s",
                call_sid or "?",
                exc,
            )
            twiml = _build_voice_say_only_twiml(
                "Desculpe, o atendimento por voz não está disponível no momento."
            )
            return Response(content=twiml, media_type="application/xml")
        twiml = _build_voice_connect_stream_twiml(wss_url)
        return Response(content=twiml, media_type="application/xml")

    if mode != "record":
        logger.warning(
            "Voice inbound mode %r not implemented; only record and stream are supported",
            mode,
        )
        twiml = _build_voice_say_only_twiml(
            "Este modo de atendimento por voz ainda não está disponível."
        )
        return Response(content=twiml, media_type="application/xml")

    return await _voice_inbound_record_response(
        call_sid=call_sid,
        from_number=from_number,
        to=(To or "").strip(),
    )


@router.websocket("/webhooks/voice/media-stream")
async def voice_media_stream_ws(websocket: WebSocket) -> None:
    """Twilio Media Streams — transport only (Fase A)."""
    await handle_voice_media_stream(websocket)


@router.get("/webhooks/voice/inbound/record-callback")
@router.post("/webhooks/voice/inbound/record-callback")
async def voice_inbound_record_callback(
    CallSid: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingDuration: str = Form(""),
):
    """Enfileira turno assíncrono (Celery) e responde rápido com Redirect para turn-ready."""
    call_sid = (CallSid or "").strip()
    from_number = _resolve_voice_customer_number(call_sid, From or "", To or "")

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

        silence_reason = _voice_silence_reason(recording_url, duration)
        if silence_reason:
            logger.info(
                "Voice record-callback silence reason=%s call_sid=%s duration=%s url_present=%s",
                silence_reason,
                call_sid or "?",
                duration,
                bool(recording_url),
            )
            twiml = await _handle_voice_silence_turn(
                call_sid=call_sid,
                from_number=from_number,
            )
            return _twiml_response(twiml)

        if not call_sid:
            logger.warning("Voice record-callback sem CallSid; fallback erro")
            twiml = _build_voice_turn_twiml(
                VOICE_ERROR_MESSAGE,
                is_fallback=True,
            )
            return _twiml_response(twiml)

        turn_id = str(uuid.uuid4())
        await _enqueue_voice_inbound_turn(
            call_sid=call_sid,
            turn_id=turn_id,
            recording_url=recording_url,
            from_number=from_number,
            duration=duration,
        )
        twiml = _build_voice_turn_redirect_twiml(call_sid=call_sid, turn_id=turn_id)
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
        )
        return _twiml_response(twiml)


@router.get("/webhooks/voice/inbound/turn-ready")
@router.post("/webhooks/voice/inbound/turn-ready")
async def voice_inbound_turn_ready(
    call_sid: str = Query("", alias="call_sid"),
    turn_id: str = Query("", alias="turn_id"),
):
    """Polling Redis — pending: Pause+Redirect; ready: Play+Record; error/silence tratados."""
    sid = (call_sid or "").strip()
    tid = (turn_id or "").strip()

    if not sid or not tid:
        return _twiml_response(_build_voice_turn_timeout_twiml())

    turn = await asyncio.to_thread(get_voice_turn, sid, tid)
    if turn is None:
        logger.warning("Voice turn-ready missing call_sid=%s turn_id=%s", sid, tid)
        return _twiml_response(_build_voice_turn_timeout_twiml())

    status = (turn.get("status") or "").strip().lower()

    if status == "consumed":
        logger.info("Voice turn-ready already consumed call_sid=%s turn_id=%s", sid, tid)
        return _twiml_response(
            _build_voice_turn_twiml(
                VOICE_ERROR_MESSAGE,
                is_fallback=True,
            )
        )

    if status == "pending":
        poll_count = await asyncio.to_thread(increment_turn_poll_count, sid, tid)
        max_polls = max(1, int(settings.voice_turn_max_poll_attempts))
        if poll_count >= max_polls:
            await asyncio.to_thread(mark_turn_error, sid, tid, error="poll_timeout")
            await asyncio.to_thread(mark_turn_consumed, sid, tid)
            logger.warning(
                "Voice turn poll timeout call_sid=%s turn_id=%s polls=%s",
                sid,
                tid,
                poll_count,
            )
            return _twiml_response(_build_voice_turn_timeout_twiml())
        return _twiml_response(
            _build_voice_poll_twiml(
                call_sid=sid,
                turn_id=tid,
                play_wait=(poll_count == 1),
            )
        )

    if status == "silence_stt":
        await asyncio.to_thread(mark_turn_consumed, sid, tid)
        from_number = (turn.get("from_number") or "").strip()
        twiml = await _handle_voice_silence_turn(
            call_sid=sid,
            from_number=from_number,
        )
        return _twiml_response(twiml)

    if status == "ready":
        audio_filename = (turn.get("audio_filename") or "").strip()
        wait_total_ms = _compute_wait_total_ms(turn)
        poll_attempts = int(turn.get("poll_count") or 0)
        await asyncio.to_thread(mark_turn_consumed, sid, tid)
        if not audio_filename or not _is_served_audio_filename(audio_filename):
            logger.warning(
                "Voice turn ready but invalid audio call_sid=%s turn_id=%s file=%r",
                sid,
                tid,
                audio_filename,
            )
            return _twiml_response(
                _build_voice_turn_twiml(
                    VOICE_ERROR_MESSAGE,
                    is_fallback=True,
                )
            )
        logger.info(
            "Voice turn delivered call_sid=%s turn_id=%s wait_total_ms=%s "
            "poll_attempts=%s audio=%s hangup=%s",
            sid,
            tid,
            f"{wait_total_ms:.0f}" if wait_total_ms is not None else "?",
            poll_attempts,
            audio_filename,
            bool(turn.get("should_hangup")),
        )
        if turn.get("should_hangup"):
            from_number = (turn.get("from_number") or "").strip()
            from app.core.database import AsyncSessionLocal
            from app.services.voice_call_finalize import (
                VOICE_FAREWELL_ORIGEM,
                finalize_voice_call_terminal,
            )
            from app.services.voice_call_state import clear_voice_call_state

            async with AsyncSessionLocal() as session:
                await finalize_voice_call_terminal(
                    session,
                    call_sid=sid,
                    from_number=from_number or None,
                    origem=VOICE_FAREWELL_ORIGEM,
                )
                await session.commit()
            clear_voice_call_state(sid)
            twiml = _build_voice_hangup_twiml(audio_filename, is_fallback=False)
            return _twiml_response(twiml)

        twiml = _build_voice_turn_twiml(
            audio_filename,
            is_fallback=False,
        )
        return _twiml_response(twiml)

    if status == "error":
        await asyncio.to_thread(mark_turn_consumed, sid, tid)
        return _twiml_response(
            _build_voice_turn_twiml(
                VOICE_ERROR_MESSAGE,
                is_fallback=True,
            )
        )

    logger.warning(
        "Voice turn-ready unknown status=%r call_sid=%s turn_id=%s",
        status,
        sid,
        tid,
    )
    return _twiml_response(_build_voice_turn_timeout_twiml())


@router.get("/webhooks/voice/inbound/status")
@router.post("/webhooks/voice/inbound/status")
async def voice_inbound_status_callback(
    db: AsyncSession = Depends(get_db),
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    """Twilio StatusCallback — finaliza LI se o cliente desligar sem terminal."""
    from app.services.voice_call_finalize import finalize_voice_call_terminal
    from app.services.voice_call_state import clear_voice_call_state

    call_sid = (CallSid or "").strip()
    status = (CallStatus or "").strip().lower()
    from_number = _resolve_voice_customer_number(call_sid, From or "", To or "")

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


@router.post("/webhooks/whatsapp/status")
async def whatsapp_status_webhook(
    db: AsyncSession = Depends(get_db),
    MessageSid: str = Form(""),
    MessageStatus: str = Form(""),
    SmsStatus: str = Form(""),
    ErrorCode: str = Form(""),
    ErrorMessage: str = Form(""),
):
    """
    Twilio status callback de entrega WhatsApp (queued → sent → delivered / failed).

    Campos principais: MessageSid, MessageStatus (ou SmsStatus), ErrorCode, ErrorMessage.
    """
    from app.services.whatsapp_delivery import apply_whatsapp_delivery_status

    status = (MessageStatus or SmsStatus or "").strip()
    err_code = (ErrorCode or "").strip() or None

    logger.info(
        "WhatsApp status callback MessageSid=%s MessageStatus=%s ErrorCode=%s ErrorMessage=%s",
        MessageSid or "?",
        status or "?",
        err_code or "?",
        (ErrorMessage or "?")[:120],
    )

    await apply_whatsapp_delivery_status(
        db,
        message_sid=MessageSid,
        message_status=status,
        error_code=err_code,
    )
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
