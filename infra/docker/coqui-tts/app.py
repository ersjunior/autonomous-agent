"""REST API for Coqui XTTS-v2 text-to-speech (Portuguese)."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Deve existir antes do import/instantiate do TTS (download do modelo).
os.environ.setdefault("COQUI_TOS_AGREED", "1")

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from TTS.api import TTS

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

MODEL_NAME = os.getenv(
    "COQUI_MODEL",
    "tts_models/multilingual/multi-dataset/xtts_v2",
)
DEFAULT_SPEAKER = os.getenv("COQUI_VOICE_SAMPLE", "")
DEVICE = os.getenv("COQUI_DEVICE", "cuda").strip().lower()

_tts: TTS | None = None
_model_ready = False
_model_error: str | None = None
_latents_api_available: bool | None = None

# path_resolved -> (gpt_cond_latent, speaker_embedding, mtime)
_speaker_latent_cache: dict[str, tuple[Any, Any, float]] = {}


def _use_gpu() -> bool:
    return DEVICE in ("cuda", "gpu")


def get_tts() -> TTS:
    global _tts
    if _tts is None:
        # Coqui TTS 0.22.x: parâmetro gpu=True no construtor (não .to("cuda")).
        _tts = TTS(MODEL_NAME, gpu=_use_gpu())
    return _tts


def _get_xtts_model(tts: TTS) -> Any | None:
    """Modelo XTTS subjacente (suporta get_conditioning_latents + inference)."""
    global _latents_api_available
    model = getattr(getattr(tts, "synthesizer", None), "tts_model", None)
    if model is None or not hasattr(model, "get_conditioning_latents"):
        _latents_api_available = False
        return None
    if not hasattr(model, "inference"):
        _latents_api_available = False
        return None
    _latents_api_available = True
    return model


def _speaker_cache_key(speaker_path: str) -> str:
    return str(Path(speaker_path).resolve())


def _load_speaker_latents(
    xtts_model: Any,
    speaker_path: str,
) -> tuple[Any, Any, float, bool]:
    """Retorna (gpt_cond_latent, speaker_embedding, speaker_ms, cache_hit)."""
    key = _speaker_cache_key(speaker_path)
    mtime = Path(speaker_path).stat().st_mtime
    cached = _speaker_latent_cache.get(key)
    if cached is not None and cached[2] == mtime:
        return cached[0], cached[1], 0.0, True

    t0 = time.perf_counter()
    gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
        audio_path=[speaker_path],
    )
    speaker_ms = (time.perf_counter() - t0) * 1000
    _speaker_latent_cache[key] = (gpt_cond_latent, speaker_embedding, mtime)
    return gpt_cond_latent, speaker_embedding, speaker_ms, False


def _write_inference_wav(out: dict[str, Any], out_path: str) -> None:
    wav = np.asarray(out["wav"], dtype=np.float32)
    sample_rate = int(out.get("sample_rate") or 24000)
    sf.write(out_path, wav, sample_rate)


def _synthesize_to_wav(
    tts: TTS,
    *,
    text: str,
    speaker_path: str,
    language: str,
    out_path: str,
) -> tuple[float, float, bool]:
    """
    Sintetiza WAV via latents cacheados (XTTS inference).

    Returns:
        (speaker_ms, synth_ms, speaker_cache_hit)
    """
    xtts = _get_xtts_model(tts)
    if xtts is None:
        raise RuntimeError("XTTS latents API unavailable")

    gpt_cond_latent, speaker_embedding, speaker_ms, cached = _load_speaker_latents(
        xtts, speaker_path
    )

    t0 = time.perf_counter()
    out = xtts.inference(
        text,
        language,
        gpt_cond_latent,
        speaker_embedding,
        enable_text_splitting=True,
    )
    synth_ms = (time.perf_counter() - t0) * 1000
    _write_inference_wav(out, out_path)
    return speaker_ms, synth_ms, cached


def _synthesize_to_wav_fallback(
    tts: TTS,
    *,
    text: str,
    speaker_path: str,
    language: str,
    out_path: str,
) -> tuple[float, float, bool]:
    """Fallback: tts_to_file (reprocessa speaker a cada chamada)."""
    t0 = time.perf_counter()
    tts.tts_to_file(
        text=text,
        file_path=out_path,
        speaker_wav=speaker_path,
        language=language,
    )
    combined_ms = (time.perf_counter() - t0) * 1000
    return 0.0, combined_ms, False


def _warmup_synthesis() -> None:
    speaker_path = DEFAULT_SPEAKER
    if not speaker_path or not Path(speaker_path).is_file():
        return

    tts = get_tts()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name

    try:
        xtts = _get_xtts_model(tts)
        if xtts is not None:
            _load_speaker_latents(xtts, speaker_path)
            speaker_ms, synth_ms, cached = _synthesize_to_wav(
                tts,
                text="Ok.",
                speaker_path=speaker_path,
                language="pt",
                out_path=out_path,
            )
            logger.info(
                "TTS warmup speaker_ms=%.0f synth_ms=%.0f chars=2 cached=%s",
                speaker_ms,
                synth_ms,
                str(cached).lower(),
            )
        else:
            _synthesize_to_wav_fallback(
                tts,
                text="Ok.",
                speaker_path=speaker_path,
                language="pt",
                out_path=out_path,
            )
            logger.warning("TTS warmup via tts_to_file fallback (latents API unavailable)")
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


def _wav_to_pcm_wav(wav_path: str, sample_rate: int) -> bytes:
    """WAV XTTS → WAV mono PCM16 no sample rate pedido (ex.: 8 kHz para Media Streams)."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            wav_path,
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "wav",
            "pipe:1",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"ffmpeg failed to resample audio: {proc.stderr.decode(errors='ignore')[:500]}",
        )
    if not proc.stdout:
        raise HTTPException(status_code=500, detail="ffmpeg returned empty WAV")
    return proc.stdout


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
    # None → MP3 mono 16 kHz (record/Twilio Play). 8000 → WAV mono PCM16 @ 8 kHz (stream μ-law).
    sample_rate: int | None = Field(default=None)


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
                "latents_cache": _latents_api_available,
                "error": _model_error,
            },
        )
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_loaded": True,
        "device": DEVICE,
        "cuda_available": _torch_cuda_available(),
        "latents_cache": _latents_api_available,
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

    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    chars = len(text)
    tts = get_tts()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name

    speaker_ms = 0.0
    synth_ms = 0.0
    ffmpeg_ms = 0.0
    cached = False
    used_fallback = False

    try:
        try:
            speaker_ms, synth_ms, cached = _synthesize_to_wav(
                tts,
                text=text,
                speaker_path=speaker_path,
                language=request.language,
                out_path=out_path,
            )
        except Exception as exc:
            logger.warning(
                "XTTS latents synthesis failed; falling back to tts_to_file: %s",
                exc,
            )
            used_fallback = True
            speaker_ms, synth_ms, cached = _synthesize_to_wav_fallback(
                tts,
                text=text,
                speaker_path=speaker_path,
                language=request.language,
                out_path=out_path,
            )

        t0 = time.perf_counter()
        target_rate = request.sample_rate
        if target_rate is not None and int(target_rate) == 8000:
            audio_bytes = _wav_to_pcm_wav(out_path, 8000)
            media_type = "audio/wav"
        else:
            audio_bytes = _wav_to_telephony_mp3(out_path)
            media_type = "audio/mpeg"
        ffmpeg_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "TTS timing speaker_ms=%.0f synth_ms=%.0f ffmpeg_ms=%.0f "
            "chars=%s cached=%s fallback=%s sample_rate=%s",
            speaker_ms,
            synth_ms,
            ffmpeg_ms,
            chars,
            str(cached).lower(),
            str(used_fallback).lower(),
            target_rate if target_rate is not None else "16000_mp3",
        )
        return Response(content=audio_bytes, media_type=media_type)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
