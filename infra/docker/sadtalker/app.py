"""
REST API SadTalker (imagem + áudio → vídeo MP4).

Contrato C.1 (Entrega C.2 ajustará sadtalker_provider.py):
  POST /generate — multipart: image + audio → salva MP4 em volume, retorna video_filename.
  O provider legado {text, avatar_id} não reflete o pipeline real do SadTalker.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SADTALKER_ROOT = Path(os.getenv("SADTALKER_ROOT", "/opt/SadTalker"))
CHECKPOINT_DIR = SADTALKER_ROOT / "checkpoints"
VIDEOS_DIR = Path(os.getenv("AVATAR_VIDEOS_DIR", "/data/videos"))
AVATARS_DIR = Path(os.getenv("AVATARS_DIR", "/avatars"))
SADTALKER_SIZE = int(os.getenv("SADTALKER_SIZE", "256"))

REQUIRED_CHECKPOINTS = (
    "SadTalker_V0.0.2_256.safetensors",
    "mapping_00109-model.pth.tar",
    "mapping_00229-model.pth.tar",
)

_model_ready = False
_model_error: str | None = None
_gpu_available = False

# Pipeline SadTalker (carregado no lifespan)
_preprocess_model = None
_audio_to_coeff = None
_animate_from_coeff = None


def _ensure_sadtalker_path() -> None:
    root = str(SADTALKER_ROOT.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _check_checkpoints() -> list[str]:
    missing = [name for name in REQUIRED_CHECKPOINTS if not (CHECKPOINT_DIR / name).is_file()]
    return missing


def _load_sadtalker_models() -> None:
    """Carrega pesos no GPU (mesmo fluxo que inference.py)."""
    global _preprocess_model, _audio_to_coeff, _animate_from_coeff

    _ensure_sadtalker_path()
    from src.facerender.animate import AnimateFromCoeff
    from src.test_audio2coeff import Audio2Coeff
    from src.utils.init_path import init_path
    from src.utils.preprocess import CropAndExtract

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        raise RuntimeError("SadTalker exige CUDA — GPU não visível no container")

    sadtalker_paths = init_path(
        str(CHECKPOINT_DIR),
        str(SADTALKER_ROOT / "src" / "config"),
        SADTALKER_SIZE,
        old_version=False,
        preprocess="crop",
    )

    _preprocess_model = CropAndExtract(sadtalker_paths, device)
    _audio_to_coeff = Audio2Coeff(sadtalker_paths, device)
    _animate_from_coeff = AnimateFromCoeff(sadtalker_paths, device)
    logger.info("SadTalker models loaded on %s", device)


def _run_inference(image_path: Path, audio_path: Path, result_dir: Path) -> Path:
    """Gera MP4 com o pipeline já carregado."""
    from time import strftime

    from src.generate_batch import get_data
    from src.generate_facerender_batch import get_facerender_data

    if _preprocess_model is None or _audio_to_coeff is None or _animate_from_coeff is None:
        raise RuntimeError("SadTalker pipeline not initialized")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    save_dir = result_dir / strftime("%Y_%m_%d_%H.%M.%S")
    save_dir.mkdir(parents=True, exist_ok=True)

    first_frame_dir = save_dir / "first_frame_dir"
    first_frame_dir.mkdir(exist_ok=True)

    first_coeff_path, crop_pic_path, crop_info = _preprocess_model.generate(
        str(image_path),
        str(first_frame_dir),
        "crop",
        source_image_flag=True,
        pic_size=SADTALKER_SIZE,
    )
    if first_coeff_path is None:
        raise RuntimeError("Não foi possível extrair coeficientes da imagem de entrada")

    batch = get_data(first_coeff_path, str(audio_path), device, ref_eyeblink_coeff_path=None, still=False)
    coeff_path = _audio_to_coeff.generate(batch, str(save_dir), 0, ref_pose_coeff_path=None)

    data = get_facerender_data(
        coeff_path,
        crop_pic_path,
        first_coeff_path,
        str(audio_path),
        2,
        None,
        None,
        None,
        expression_scale=1.0,
        still_mode=False,
        preprocess="crop",
        size=SADTALKER_SIZE,
    )

    result = _animate_from_coeff.generate(
        data,
        str(save_dir),
        str(image_path),
        crop_info,
        enhancer=None,
        background_enhancer=None,
        preprocess="crop",
        img_size=SADTALKER_SIZE,
    )

    out_mp4 = Path(str(save_dir) + ".mp4")
    shutil.move(result, out_mp4)
    shutil.rmtree(save_dir, ignore_errors=True)
    return out_mp4


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_ready, _model_error, _gpu_available

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    _gpu_available = torch.cuda.is_available()
    missing = _check_checkpoints()
    if missing:
        _model_error = f"Checkpoints ausentes: {', '.join(missing)}"
        logger.error(_model_error)
        yield
        return

    try:
        _load_sadtalker_models()
        _model_ready = True
        logger.info(
            "SadTalker ready — GPU=%s device=%s",
            _gpu_available,
            torch.cuda.get_device_name(0) if _gpu_available else "n/a",
        )
    except Exception as exc:
        _model_error = str(exc)
        logger.exception("Falha ao carregar SadTalker: %s", exc)

    yield


app = FastAPI(title="sadtalker", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    payload = {
        "status": "ok" if _model_ready and _gpu_available else "loading",
        "model_loaded": _model_ready,
        "gpu": _gpu_available,
        "device": torch.cuda.get_device_name(0) if _gpu_available else None,
        "sadtalker_root": str(SADTALKER_ROOT),
        "error": _model_error,
    }
    if not _model_ready or not _gpu_available:
        return JSONResponse(status_code=503, content=payload)
    return JSONResponse(content=payload)


@app.post("/generate")
async def generate(
    image: UploadFile = File(..., description="Imagem do rosto (PNG/JPG)"),
    audio: UploadFile = File(..., description="Áudio que dirige a fala (WAV/MP3)"),
) -> dict:
    """
    Gera vídeo talking-head (lip-sync). Salva em AVATAR_VIDEOS_DIR e retorna o nome do arquivo.

    Entrega C.2: o avatar_provider enviará áudio do Coqui + imagem do avatar_id.
    """
    if not _model_ready:
        raise HTTPException(
            status_code=503,
            detail={"message": "SadTalker ainda carregando", "error": _model_error},
        )

    image_suffix = Path(image.filename or "image.png").suffix or ".png"
    audio_suffix = Path(audio.filename or "audio.wav").suffix or ".wav"

    work = Path(tempfile.mkdtemp(prefix="sadtalker_"))
    try:
        image_path = work / f"source{image_suffix}"
        audio_path = work / f"driven{audio_suffix}"
        image_path.write_bytes(await image.read())
        audio_path.write_bytes(await audio.read())

        result_dir = work / "results"
        result_dir.mkdir()
        out_mp4 = _run_inference(image_path, audio_path, result_dir)

        filename = f"{uuid.uuid4()}.mp4"
        dest = VIDEOS_DIR / filename
        shutil.copy2(out_mp4, dest)
        if dest.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="MP4 gerado está vazio")

        return {
            "video_filename": filename,
            "status": "done",
            "path": str(dest),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/videos")
async def videos_legacy() -> dict:
    raise HTTPException(
        status_code=501,
        detail="Use POST /generate com multipart image+audio",
    )
