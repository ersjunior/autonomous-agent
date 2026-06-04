"""Geração de áudio para chamadas outbound (Coqui → MP3 telefonia)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from agents.channels.voice.tts_stt import text_to_speech
from app.core.config import settings

TELEPHONY_SAMPLE_RATE = "16000"


def _guess_input_suffix(audio_bytes: bytes) -> str:
    if audio_bytes[:4] == b"RIFF":
        return ".wav"
    if audio_bytes[:3] == b"ID3" or (
        len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0
    ):
        return ".mp3"
    return ".wav"


def _transcode_to_telephony_mp3(audio_bytes: bytes) -> bytes:
    """Converte WAV/MP3 de entrada em MP3 mono 16 kHz (telefonia)."""
    suffix = _guess_input_suffix(audio_bytes)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        input_path = tmp.name

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                TELEPHONY_SAMPLE_RATE,
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "5",
                "-f",
                "mp3",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
    finally:
        os.unlink(input_path)

    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="ignore")[:500]
        raise RuntimeError(f"ffmpeg falhou ao converter áudio para MP3 telefonia: {stderr}")

    if not proc.stdout:
        raise RuntimeError("ffmpeg retornou MP3 vazio")

    return proc.stdout


async def gerar_audio_chamada(text: str) -> str:
    """Sintetiza voz clonada (Coqui), converte para MP3 telefonia e salva no volume.

    Returns:
        Nome do arquivo (ex.: ``{uuid}.mp3``), não o path completo.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Texto vazio para síntese de áudio da chamada")

    try:
        audio_bytes = await text_to_speech(cleaned)
    except Exception as exc:
        raise RuntimeError(f"Falha ao sintetizar áudio no Coqui: {exc}") from exc

    if not audio_bytes:
        raise RuntimeError("Coqui retornou áudio vazio")

    try:
        mp3_bytes = _transcode_to_telephony_mp3(audio_bytes)
    except Exception as exc:
        raise RuntimeError(f"Falha na conversão do áudio para MP3 telefonia: {exc}") from exc

    root = Path(settings.voice_audio_root)
    root.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4()}.mp3"
    dest = root / filename
    dest.write_bytes(mp3_bytes)

    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Arquivo MP3 gerado está vazio")

    return filename
