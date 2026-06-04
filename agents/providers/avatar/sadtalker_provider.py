"""SadTalker local avatar provider — imagem + áudio (Coqui) → MP4."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from agents.channels.voice.tts_stt import text_to_speech
from agents.providers.base import AvatarProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

GENERATE_TIMEOUT_SEC = 600.0


def _guess_audio_filename(audio_bytes: bytes) -> str:
    if audio_bytes[:4] == b"RIFF":
        return "speech.wav"
    if audio_bytes[:3] == b"ID3" or (
        len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0
    ):
        return "speech.mp3"
    return "speech.wav"


def _resolve_avatar_image_path(avatar_ref: str) -> Path:
    """Resolve face image under settings.avatars_root (basename only, no path traversal)."""
    ref = (avatar_ref or "").strip()
    if not ref:
        raise ValueError("avatar_ref vazio — informe o nome do arquivo de rosto em avatars/")

    name = Path(ref).name
    if name != ref and "/" in ref.replace("\\", "/"):
        logger.warning("avatar_ref com path ignorado; usando basename=%s", name)

    root = Path(settings.avatars_root)
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(
            f"Imagem de avatar não encontrada: {path} (avatars_root={root})"
        )
    return path


class SadTalkerAvatarProvider(AvatarProvider):
    """
    Talking avatar via local SadTalker REST service (POST /generate).

    Geração síncrona: ``create_video`` já retorna o MP4 pronto em ``avatar_video_root``.
    ``get_video`` apenas confirma que o arquivo existe no volume compartilhado.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.sadtalker_base_url.rstrip("/"),
            timeout=httpx.Timeout(GENERATE_TIMEOUT_SEC),
        )

    @property
    def provider_name(self) -> str:
        return "sadtalker"

    async def _ensure_audio(self, text: str, audio_bytes: bytes | None) -> bytes:
        if audio_bytes:
            return audio_bytes
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Texto vazio e sem audio_bytes para SadTalker")
        audio = await text_to_speech(cleaned)
        if not audio:
            raise RuntimeError("Coqui retornou áudio vazio para SadTalker")
        return audio

    async def create_video(
        self,
        text: str,
        avatar_ref: str,
        audio_bytes: bytes | None = None,
    ) -> dict:
        image_path = _resolve_avatar_image_path(avatar_ref)
        audio = await self._ensure_audio(text, audio_bytes)
        audio_name = _guess_audio_filename(audio)

        image_bytes = image_path.read_bytes()
        suffix = image_path.suffix.lower() or ".png"
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"

        response = await self._client.post(
            "/generate",
            files={
                "image": (image_path.name, image_bytes, mime),
                "audio": (audio_name, audio, "audio/wav" if audio_name.endswith(".wav") else "audio/mpeg"),
            },
        )
        response.raise_for_status()
        data = response.json()

        video_filename = data.get("video_filename") or data.get("id", "")
        status = data.get("status", "done")

        return {
            "id": video_filename,
            "status": status,
            "video_filename": video_filename,
        }

    async def get_video(self, video_id: str) -> dict:
        """SadTalker é síncrono — confirma MP4 no volume local (sem polling HTTP)."""
        name = Path(video_id).name
        path = Path(settings.avatar_video_root) / name
        if path.is_file() and path.stat().st_size > 0:
            return {
                "id": name,
                "status": "done",
                "video_filename": name,
            }
        return {
            "id": name,
            "status": "not_found",
            "video_filename": name,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
