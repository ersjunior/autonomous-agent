"""REST API for local faster-whisper transcription."""

import os
import tempfile
import wave
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel

MODEL_SIZE = os.getenv("WHISPER_MODEL", "large-v3")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

_model: WhisperModel | None = None
_model_ready = False
_model_error: str | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def _write_silence_wav(path: str, duration_sec: float = 1.0, rate: int = 16000) -> None:
    nframes = int(rate * duration_sec)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * nframes)


def _warmup_transcription() -> None:
    model = get_model()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        silence_path = tmp.name

    try:
        _write_silence_wav(silence_path, duration_sec=1.0)
        segments, _info = model.transcribe(silence_path, language="pt")
        for _ in segments:
            pass
    finally:
        if os.path.exists(silence_path):
            os.unlink(silence_path)


def _cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready, _model_error
    try:
        _warmup_transcription()
        _model_ready = True
    except Exception as exc:
        _model_error = str(exc)
    yield


app = FastAPI(title="faster-whisper", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str | int | bool]:
    if not _model_ready:
        return {
            "status": "loading",
            "model": MODEL_SIZE,
            "device": DEVICE,
            "compute_type": COMPUTE_TYPE,
            "cuda_devices": _cuda_device_count(),
            "model_loaded": False,
            "error": _model_error or "",
        }
    return {
        "status": "ok",
        "model": MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "cuda_devices": _cuda_device_count(),
        "model_loaded": True,
    }


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("pt"),
) -> dict[str, str]:
    if not _model_ready:
        raise HTTPException(status_code=503, detail=_model_error or "Modelo STT ainda não carregado")

    raw = await audio.read()
    suffix = ".mp3"
    if audio.filename and "." in audio.filename:
        suffix = "." + audio.filename.rsplit(".", 1)[-1]

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        model = get_model()
        segments, _info = model.transcribe(
            tmp_path,
            language=language if language else None,
        )
        text = " ".join(segment.text.strip() for segment in segments)
        return {"text": text.strip(), "language": language}
    finally:
        os.unlink(tmp_path)
