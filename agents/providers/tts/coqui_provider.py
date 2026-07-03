"""Coqui XTTS-v2 local TTS provider."""

import httpx

from agents.providers.base import TTSProvider
from app.core.config import settings


class CoquiTTSProvider(TTSProvider):
    """Text-to-speech via local Coqui XTTS-v2 REST service.

    O serviço transcodifica o áudio para MP3 (audio/mpeg) antes de responder,
    mantendo o mesmo contrato de saída do provider ElevenLabs.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.coqui_base_url.rstrip("/"),
            timeout=httpx.Timeout(180.0),
        )

    @property
    def provider_name(self) -> str:
        return "coqui"

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        *,
        sample_rate: int | None = None,
    ) -> bytes:
        speaker = voice_id or settings.coqui_voice_sample or ""
        payload: dict[str, str | int] = {
            "text": text,
            "language": "pt",
            "speaker_wav": speaker,
        }
        if sample_rate is not None:
            payload["sample_rate"] = int(sample_rate)
        response = await self._client.post("/tts", json=payload)
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()
