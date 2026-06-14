"""OpenAI Whisper API STT provider."""

import io

from openai import AsyncOpenAI

from agents.providers.base import STTProvider
from app.core.config import settings


class OpenAISTTProvider(STTProvider):
    """Speech-to-text via OpenAI Whisper API."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "pt",
        *,
        filename: str = "audio.mp3",
        content_type: str = "audio/mpeg",
    ) -> str:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.mp3"
        transcription = await self._client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,
        )
        return transcription.text

    async def aclose(self) -> None:
        await self._client.close()
