"""Text-to-Speech and Speech-to-Text utilities."""

import io

import httpx
from openai import AsyncOpenAI

from app.core.config import settings


async def speech_to_text(audio_bytes: bytes) -> str:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.mp3"
    transcription = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return transcription.text


async def text_to_speech(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}"
    async with httpx.AsyncClient() as client:
        response = await client.post(
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
