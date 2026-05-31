"""Text-to-Speech and Speech-to-Text utilities."""

from agents.provider_factory import ProviderFactory


async def speech_to_text(audio_bytes: bytes) -> str:
    stt = ProviderFactory.get_stt()
    return await stt.transcribe(audio_bytes, language="pt")


async def text_to_speech(text: str) -> bytes:
    tts = ProviderFactory.get_tts()
    return await tts.synthesize(text)
