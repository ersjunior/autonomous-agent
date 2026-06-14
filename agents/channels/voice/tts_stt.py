"""Text-to-Speech and Speech-to-Text utilities."""

from agents.provider_factory import ProviderFactory


async def speech_to_text(
    audio_bytes: bytes,
    language: str = "pt",
    *,
    filename: str = "audio.mp3",
    content_type: str = "audio/mpeg",
) -> str:
    stt = ProviderFactory.get_stt()
    return await stt.transcribe(
        audio_bytes,
        language=language,
        filename=filename,
        content_type=content_type,
    )


async def text_to_speech(text: str) -> bytes:
    tts = ProviderFactory.get_tts()
    return await tts.synthesize(text)
