"""faster-whisper local STT provider."""

import httpx

from agents.providers.base import STTProvider
from app.core.config import settings


class FasterWhisperSTTProvider(STTProvider):
    """Speech-to-text via local faster-whisper REST service."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.whisper_base_url.rstrip("/"),
            timeout=httpx.Timeout(120.0),
        )

    @property
    def provider_name(self) -> str:
        return "faster_whisper"

    async def transcribe(
        self, audio_bytes: bytes, language: str = "pt"
    ) -> str:
        response = await self._client.post(
            "/transcribe",
            files={"audio": ("audio.mp3", audio_bytes, "audio/mpeg")},
            data={"language": language},
        )
        response.raise_for_status()
        data = response.json()
        return data["text"]

    async def aclose(self) -> None:
        await self._client.aclose()
