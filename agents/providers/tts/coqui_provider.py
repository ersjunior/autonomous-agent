"""Coqui XTTS-v2 local TTS provider."""

import httpx

from agents.providers.base import TTSProvider
from app.core.config import settings


class CoquiTTSProvider(TTSProvider):
    """Text-to-speech via local Coqui XTTS-v2 REST service."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.coqui_base_url.rstrip("/"),
            timeout=httpx.Timeout(180.0),
        )

    @property
    def provider_name(self) -> str:
        return "coqui"

    async def synthesize(
        self, text: str, voice_id: str | None = None
    ) -> bytes:
        speaker = voice_id or settings.coqui_voice_sample or ""
        response = await self._client.post(
            "/tts",
            json={
                "text": text,
                "language": "pt",
                "speaker_wav": speaker,
            },
        )
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()
