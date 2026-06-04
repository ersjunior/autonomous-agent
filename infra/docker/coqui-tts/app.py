"""REST API for Coqui XTTS-v2 text-to-speech (Portuguese)."""

import os

# Deve existir antes do import/instantiate do TTS (download do modelo).
os.environ.setdefault("COQUI_TOS_AGREED", "1")

import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from TTS.api import TTS

MODEL_NAME = os.getenv(
    "COQUI_MODEL",
    "tts_models/multilingual/multi-dataset/xtts_v2",
)
DEFAULT_SPEAKER = os.getenv("COQUI_VOICE_SAMPLE", "")

_tts: TTS | None = None
_model_ready = False
_model_error: str | None = None


def get_tts() -> TTS:
    global _tts
    if _tts is None:
        _tts = TTS(MODEL_NAME)
    return _tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready, _model_error
    try:
        get_tts()
        _model_ready = True
    except Exception as exc:
        _model_error = str(exc)
    yield


app = FastAPI(title="coqui-tts", version="1.0.0", lifespan=lifespan)


def _wav_to_mp3(wav_path: str) -> bytes:
    """Transcode a WAV file to MP3 bytes using the bundled ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "pipe:1"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"ffmpeg failed to transcode audio: {proc.stderr.decode(errors='ignore')[:500]}",
        )
    return proc.stdout


class TTSRequest(BaseModel):
    text: str
    language: str = Field(default="pt")
    speaker_wav: str = ""


@app.get("/health")
async def health() -> dict:
    if not _model_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "loading",
                "model": MODEL_NAME,
                "model_loaded": False,
                "error": _model_error,
            },
        )
    return {"status": "ok", "model": MODEL_NAME, "model_loaded": True}


@app.post("/tts")
async def synthesize(request: TTSRequest) -> Response:
    if not _model_ready:
        raise HTTPException(
            status_code=503,
            detail=_model_error or "Modelo TTS ainda não carregado",
        )

    speaker_path = request.speaker_wav or DEFAULT_SPEAKER
    if not speaker_path or not Path(speaker_path).is_file():
        raise HTTPException(
            status_code=400,
            detail="speaker_wav is required (path to reference .wav for voice cloning)",
        )

    tts = get_tts()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name

    try:
        tts.tts_to_file(
            text=request.text,
            file_path=out_path,
            speaker_wav=speaker_path,
            language=request.language,
        )
        audio_bytes = _wav_to_mp3(out_path)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
