"""Twilio Voice helpers for outbound PSTN calls (TwiML via PUBLIC_BASE_URL)."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx
from twilio.rest import Client

from app.core.config import settings

logger = logging.getLogger(__name__)

VOICE_OUTBOUND_TWIML_PATH = "/api/v1/channels/webhooks/voice/outbound"
VOICE_OUTBOUND_AUDIO_TWIML_PATH = "/api/v1/channels/webhooks/voice/outbound-audio"
VOICE_AUDIO_SERVE_PATH = "/api/v1/channels/webhooks/voice/audio"

RECORDING_DOWNLOAD_RETRIES = 3
RECORDING_DOWNLOAD_RETRY_DELAY_SEC = 1.0

# MVP: texto na querystring; TODO: ?lead_interaction_id= e webhook busca no banco.
MAX_TWIML_QUERY_TEXT_CHARS = 500


def build_outbound_twiml_url(text: str) -> str:
    """Monta URL pública completa do webhook outbound com ?text= (<Say> fallback)."""
    base = settings.require_public_base_url()
    truncated = (text or "").strip()[:MAX_TWIML_QUERY_TEXT_CHARS]
    if not truncated:
        truncated = "Olá."
    query = quote(truncated, safe="")
    return f"{base}{VOICE_OUTBOUND_TWIML_PATH}?text={query}"


def build_outbound_audio_twiml_url(filename: str) -> str:
    """Monta URL pública do webhook outbound-audio com ?audio= (<Play> Coqui)."""
    base = settings.require_public_base_url()
    safe_name = quote((filename or "").strip(), safe="")
    if not safe_name:
        raise ValueError("Nome de arquivo de áudio vazio")
    return f"{base}{VOICE_OUTBOUND_AUDIO_TWIML_PATH}?audio={safe_name}"


def make_outbound_call(to: str, twiml_path: str) -> str:
    """Inicia chamada outbound. ``twiml_path`` é relativo (com query) ou URL absoluta.

    Returns:
        Twilio Call SID.
    """
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise ValueError(
            "TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN são obrigatórios para discagem de voz"
        )

    base = settings.require_public_base_url()
    if twiml_path.startswith("http://") or twiml_path.startswith("https://"):
        full_url = twiml_path
    else:
        path = twiml_path if twiml_path.startswith("/") else f"/{twiml_path}"
        full_url = f"{base}{path}"

    from_number = settings.resolve_twilio_pstn_number()
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    call = client.calls.create(to=to, from_=from_number, url=full_url)
    return call.sid


def _recording_wav_url(recording_url: str) -> str:
    base = (recording_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("RecordingUrl vazio")
    if base.lower().endswith(".wav"):
        return base
    return f"{base}.wav"


async def download_recording(recording_url: str) -> bytes:
    """Baixa gravação Twilio como WAV (HTTP Basic Auth + retry curto em 404)."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise ValueError(
            "TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN são obrigatórios para baixar gravações"
        )

    wav_url = _recording_wav_url(recording_url)
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for attempt in range(1, RECORDING_DOWNLOAD_RETRIES + 1):
            response = await client.get(wav_url, auth=auth)
            if response.status_code == 404 and attempt < RECORDING_DOWNLOAD_RETRIES:
                logger.info(
                    "Recording not ready (404), retry %s/%s: %s",
                    attempt,
                    RECORDING_DOWNLOAD_RETRIES,
                    wav_url,
                )
                await asyncio.sleep(RECORDING_DOWNLOAD_RETRY_DELAY_SEC)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                raise
            content = response.content
            if not content:
                raise RuntimeError("Gravação Twilio retornou conteúdo vazio")
            return content

    raise last_error or RuntimeError("Falha ao baixar gravação Twilio")
