"""MP3s cacheados para voz — pré-gerados no startup, nunca no hot path dos webhooks Twilio."""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.voice_silence_text import (
    VOICE_SILENCE_CLOSE_MESSAGE,
    VOICE_SILENCE_WARNING_MESSAGE,
)
from app.services.voice_audio import gerar_audio_chamada

logger = logging.getLogger(__name__)

# Curto (~1s) — reservado; record-callback NÃO bloqueia em Play.
VOICE_WAIT_FILENAME = "voice_wait_v3.mp3"
VOICE_WAIT_TEXT = "Um instante."
VOICE_WAIT_MAX_DURATION_SEC = 1.2

GREETING_CACHE_PATTERN = re.compile(r"^voice_greeting_[a-f0-9]{16}\.mp3$", re.IGNORECASE)
PHRASE_CACHE_PATTERN = re.compile(r"^voice_phrase_[a-f0-9]{16}\.mp3$", re.IGNORECASE)


def phrase_cache_filename(text: str) -> str:
    digest = hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:16]
    return f"voice_phrase_{digest}.mp3"


def is_allowed_cached_audio_filename(filename: str) -> bool:
    """Nomes fixos seguros servidos em /voice/audio/."""
    name = (filename or "").strip()
    if name == VOICE_WAIT_FILENAME:
        return True
    if PHRASE_CACHE_PATTERN.match(name):
        return True
    return bool(GREETING_CACHE_PATTERN.match(name))


def _greeting_cache_filename(greeting_text: str) -> str:
    digest = hashlib.sha256((greeting_text or "").strip().encode("utf-8")).hexdigest()[:16]
    return f"voice_greeting_{digest}.mp3"


def _trim_mp3_max_duration(path: Path, max_sec: float) -> None:
    """Recorta MP3 telefonia para duração máxima (evita espera longa se o TTS gerar silêncio)."""
    tmp = path.with_suffix(".trim.mp3")
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-t",
                str(max_sec),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "5",
                str(tmp),
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
            return
        tmp.replace(path)
    except OSError:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)


def _audio_duration_sec(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return float(proc.stdout.strip())
    except (ValueError, OSError):
        return None


def get_phrase_audio_filename(text: str) -> str | None:
    """
    Lookup read-only de MP3 cacheado por texto (webhooks — sem gerar TTS).

    Retorna None se o arquivo não existir (caller usa <Say> Polly).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    filename = phrase_cache_filename(cleaned)
    path = Path(settings.voice_audio_root) / filename
    if path.is_file() and path.stat().st_size > 0:
        return filename
    return None


async def ensure_phrase_audio_filename(text: str) -> str | None:
    """Gera MP3 cacheado por hash do texto (startup/prewarm apenas)."""
    existing = get_phrase_audio_filename(text)
    if existing:
        return existing

    cleaned = (text or "").strip()
    if not cleaned:
        return None

    filename = phrase_cache_filename(cleaned)
    root = Path(settings.voice_audio_root)
    dest = root / filename
    try:
        generated = await gerar_audio_chamada(cleaned)
        src = root / generated
        if not src.is_file():
            raise RuntimeError(f"MP3 gerado não encontrado: {generated}")
        if generated != filename:
            src.replace(dest)
        duration = _audio_duration_sec(dest)
        logger.info(
            "Voice phrase audio cached as %s duration_sec=%s",
            filename,
            f"{duration:.2f}" if duration is not None else "?",
        )
        return filename
    except Exception:
        logger.warning(
            "Falha ao gerar phrase cache %s",
            filename,
            exc_info=True,
        )
        return None


async def ensure_wait_audio_filename() -> str | None:
    """Pré-gera MP3 de espera curto (startup)."""
    root = Path(settings.voice_audio_root)
    dest = root / VOICE_WAIT_FILENAME
    if dest.is_file() and dest.stat().st_size > 0:
        return VOICE_WAIT_FILENAME

    try:
        generated = await gerar_audio_chamada(VOICE_WAIT_TEXT)
        src = root / generated
        if not src.is_file():
            raise RuntimeError(f"MP3 gerado não encontrado: {generated}")
        src.replace(dest)
        _trim_mp3_max_duration(dest, VOICE_WAIT_MAX_DURATION_SEC)
        duration = _audio_duration_sec(dest)
        logger.info(
            "Voice wait audio cached as %s duration_sec=%s",
            VOICE_WAIT_FILENAME,
            f"{duration:.2f}" if duration is not None else "?",
        )
        return VOICE_WAIT_FILENAME
    except Exception:
        logger.warning(
            "Falha ao gerar %s; áudio de espera indisponível",
            VOICE_WAIT_FILENAME,
            exc_info=True,
        )
        return None


async def prewarm_voice_wait_audio() -> None:
    """Pré-gera MP3 de espera curto no startup."""
    filename = await ensure_wait_audio_filename()
    if filename:
        dest = Path(settings.voice_audio_root) / filename
        duration = _audio_duration_sec(dest)
        logger.info(
            "Voice wait audio prewarmed file=%s duration_sec=%s",
            filename,
            f"{duration:.2f}" if duration is not None else "?",
        )
    else:
        logger.warning("Voice wait audio prewarm skipped (TTS indisponível)")


async def prewarm_silence_phrase_audio() -> None:
    """Pré-gera aviso e despedida de silêncio (mensagens fixas)."""
    for label, text in (
        ("silence_warning", VOICE_SILENCE_WARNING_MESSAGE),
        ("silence_close", VOICE_SILENCE_CLOSE_MESSAGE),
    ):
        filename = await ensure_phrase_audio_filename(text)
        if filename:
            dest = Path(settings.voice_audio_root) / filename
            duration = _audio_duration_sec(dest)
            logger.info(
                "Voice %s prewarmed file=%s duration_sec=%s",
                label,
                filename,
                f"{duration:.2f}" if duration is not None else "?",
            )
        else:
            logger.warning("Voice %s prewarm skipped (TTS indisponível)", label)


async def prewarm_voice_webhook_audio() -> None:
    """Todos os MP3s usados por webhooks Twilio (fora do hot path)."""
    await prewarm_voice_wait_audio()
    await prewarm_silence_phrase_audio()


async def ensure_greeting_audio_filename(greeting_text: str) -> str:
    """
    Retorna MP3 cacheado da saudação (por hash do texto).

    Raises se TTS falhar — caller pode fallback para <Say>.
    """
    cleaned = (greeting_text or "").strip()
    if not cleaned:
        raise ValueError("Texto de saudação vazio")

    filename = _greeting_cache_filename(cleaned)
    root = Path(settings.voice_audio_root)
    dest = root / filename
    if dest.is_file() and dest.stat().st_size > 0:
        return filename

    generated = await gerar_audio_chamada(cleaned)
    src = root / generated
    if not src.is_file():
        raise RuntimeError(f"MP3 gerado não encontrado: {generated}")
    if generated != filename:
        src.replace(dest)
    logger.info("Voice greeting cached as %s", filename)
    return filename
