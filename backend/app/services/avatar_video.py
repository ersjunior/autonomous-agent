"""Geração de vídeo avatar (Coqui + SadTalker/D-ID → MP4 no volume)."""

from __future__ import annotations

import logging
from pathlib import Path

from agents.channels.voice.tts_stt import text_to_speech
from agents.provider_factory import ProviderFactory
from app.core.config import settings

logger = logging.getLogger(__name__)


def _resolve_avatar_ref(avatar_ref: str | None) -> str:
    ref = (avatar_ref or settings.avatar_default_image or "default.png").strip()
    if not ref:
        raise ValueError("avatar_ref vazio e nenhuma imagem padrão configurada")
    image_path = Path(settings.avatars_root) / Path(ref).name
    if not image_path.is_file():
        raise FileNotFoundError(
            f"Imagem de avatar não encontrada: {image_path} "
            f"(coloque o rosto em {settings.avatars_root}/)"
        )
    return image_path.name


async def gerar_video_avatar(text: str, avatar_ref: str | None = None) -> str:
    """Sintetiza áudio (Coqui), gera talking-head e retorna o nome do MP4 no volume.

    Returns:
        Nome do arquivo (ex.: ``{uuid}.mp4``), não o path completo.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Texto vazio para geração de vídeo do avatar")

    ref = _resolve_avatar_ref(avatar_ref)

    try:
        audio_bytes = await text_to_speech(cleaned)
    except Exception as exc:
        raise RuntimeError(f"Falha ao sintetizar áudio no Coqui: {exc}") from exc

    if not audio_bytes:
        raise RuntimeError("Coqui retornou áudio vazio")

    try:
        avatar = ProviderFactory.get_avatar()
        result = await avatar.create_video(
            cleaned,
            ref,
            audio_bytes=audio_bytes,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Falha ao gerar vídeo no provedor {settings.avatar_provider!r}: {exc}"
        ) from exc

    filename = (result.get("video_filename") or result.get("id") or "").strip()
    if not filename:
        raise RuntimeError(f"Provedor de avatar não retornou video_filename: {result}")

    path = Path(settings.avatar_video_root) / Path(filename).name
    if not path.is_file():
        raise RuntimeError(
            f"MP4 não encontrado após geração: {path} "
            "(SadTalker pode estar indisponível ou volume não montado)"
        )
    if path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("Arquivo MP4 gerado está vazio")

    logger.info("Vídeo avatar gerado: %s (%s bytes)", path.name, path.stat().st_size)
    return path.name
