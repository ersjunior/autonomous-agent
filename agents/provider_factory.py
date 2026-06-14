"""Factory for LLM, STT and TTS providers based on application settings."""

from agents.providers.base import LLMProvider, STTProvider, TTSProvider
from app.core.config import settings


class ProviderFactory:
    """Instantiates the configured provider implementation (lazy imports)."""

    @staticmethod
    def get_llm() -> LLMProvider:
        provider = settings.llm_provider.lower()
        if provider == "openai":
            from agents.providers.llm.openai_provider import OpenAILLMProvider

            return OpenAILLMProvider()
        if provider == "ollama":
            from agents.providers.llm.ollama_provider import OllamaLLMProvider

            return OllamaLLMProvider()
        raise ValueError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'openai' or 'ollama'."
        )

    @staticmethod
    def get_stt() -> STTProvider:
        provider = settings.stt_provider.lower()
        if provider == "openai":
            from agents.providers.stt.openai_provider import OpenAISTTProvider

            return OpenAISTTProvider()
        if provider == "faster_whisper":
            from agents.providers.stt.faster_whisper_provider import (
                FasterWhisperSTTProvider,
            )

            return FasterWhisperSTTProvider()
        raise ValueError(
            f"Unknown STT_PROVIDER '{settings.stt_provider}'. "
            "Use 'openai' or 'faster_whisper'."
        )

    @staticmethod
    def get_tts() -> TTSProvider:
        provider = settings.tts_provider.lower()
        if provider == "elevenlabs":
            from agents.providers.tts.elevenlabs_provider import ElevenLabsTTSProvider

            return ElevenLabsTTSProvider()
        if provider == "coqui":
            from agents.providers.tts.coqui_provider import CoquiTTSProvider

            return CoquiTTSProvider()
        raise ValueError(
            f"Unknown TTS_PROVIDER '{settings.tts_provider}'. "
            "Use 'elevenlabs' or 'coqui'."
        )
