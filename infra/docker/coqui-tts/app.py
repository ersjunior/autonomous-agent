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
DEVICE = os.getenv("COQUI_DEVICE", "cuda").strip().lower()

_tts: TTS | None = None
_model_ready = False
_model_error: str | None = None


def _use_gpu() -> bool:
    return DEVICE in ("cuda", "gpu")


def get_tts() -> TTS:
    global _tts
    if _tts is None:
        # Coqui TTS 0.22.x: parâmetro gpu=True no construtor (não .to("cuda")).
        _tts = TTS(MODEL_NAME, gpu=_use_gpu())
    return _tts


def _warmup_synthesis() -> None:
    speaker_path = DEFAULT_SPEAKER
    if not speaker_path or not Path(speaker_path).is_file():
        return

    tts = get_tts()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name

    try:
        tts.tts_to_file(
            text="Ok.",
            file_path=out_path,
            speaker_wav=speaker_path,
            language="pt",
        )
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready, _model_error
    try:
        get_tts()
        _warmup_synthesis()
        _model_ready = True
    except Exception as exc:
        _model_error = str(exc)
    yield


app = FastAPI(title="coqui-tts", version="1.0.0", lifespan=lifespan)


def _torch_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _wav_to_telephony_mp3(wav_path: str) -> bytes:
    """WAV XTTS → MP3 mono 16 kHz (formato final para Twilio; evita 2º ffmpeg no backend)."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            wav_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "5",
            "-f",
            "mp3",
            "pipe:1",
        ],
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
                "device": DEVICE,
                "cuda_available": _torch_cuda_available(),
                "error": _model_error,
            },
        )
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_loaded": True,
        "device": DEVICE,
        "cuda_available": _torch_cuda_available(),
    }


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
        audio_bytes = _wav_to_telephony_mp3(out_path)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
