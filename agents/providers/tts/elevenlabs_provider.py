"""ElevenLabs TTS provider."""

import httpx

from agents.providers.base import TTSProvider
from app.core.config import settings


class ElevenLabsTTSProvider(TTSProvider):
    """Text-to-speech via ElevenLabs REST API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    async def synthesize(
        self, text: str, voice_id: str | None = None
    ) -> bytes:
        vid = voice_id or settings.elevenlabs_voice_id
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        response = await self._client.post(
            url,
            headers={
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": settings.elevenlabs_api_key or "",
            },
            json={"text": text, "model_id": "eleven_multilingual_v2"},
        )
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()
