"""Persist Coqui reference voice sample on shared volume."""

from __future__ import annotations

import io
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings

REFERENCE_FILENAME = "reference.wav"
COQUI_REFERENCE_PATH = "/voices/reference.wav"
MAX_VOICE_SAMPLE_BYTES = 10 * 1024 * 1024
MIN_WAV_DURATION_SEC = 1.0


def _validate_wav_content(content: bytes, filename: str) -> None:
    if not filename.lower().endswith(".wav"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas arquivos .wav são aceitos",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio",
        )

    if len(content) > MAX_VOICE_SAMPLE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo excede o limite de {MAX_VOICE_SAMPLE_BYTES // (1024 * 1024)}MB",
        )

    try:
        with wave.open(io.BytesIO(content), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                raise ValueError("taxa de amostragem inválida")
            duration = frames / float(rate)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo WAV inválido: {exc}",
        ) from exc

    if duration < MIN_WAV_DURATION_SEC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Amostra muito curta ({duration:.1f}s). "
                f"Use pelo menos {MIN_WAV_DURATION_SEC:.0f}s de áudio."
            ),
        )


def reference_wav_path() -> Path:
    """Fixed path to reference.wav — never parameterized from user input."""
    return Path(settings.coqui_voices_root) / REFERENCE_FILENAME


def get_reference_wav_info() -> dict[str, Any]:
    """Metadata for the current reference sample, if present."""
    path = reference_wav_path()
    if not path.is_file():
        return {
            "exists": False,
            "filename": REFERENCE_FILENAME,
            "size_bytes": 0,
            "modified_at": None,
            "path": COQUI_REFERENCE_PATH,
        }

    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return {
        "exists": True,
        "filename": REFERENCE_FILENAME,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
        "path": COQUI_REFERENCE_PATH,
    }


def save_reference_wav(content: bytes, filename: str) -> tuple[Path, int]:
    """Write reference.wav to the Coqui voices volume."""
    _validate_wav_content(content, filename)

    root = Path(settings.coqui_voices_root)
    root.mkdir(parents=True, exist_ok=True)
    dest = reference_wav_path()
    dest.write_bytes(content)

    return dest, len(content)
