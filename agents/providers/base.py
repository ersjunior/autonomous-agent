"""Abstract provider interfaces for LLM, STT and TTS services."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMProvider(ABC):
    """Contract for large language model backends."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        structured_output_schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """
        Generate a completion from a list of chat messages.

        Each message dict must include ``role`` (system/user/assistant) and
        ``content`` (str). When ``structured_output_schema`` is set, the
        implementation must return a validated Pydantic model instance.
        """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for semantic search."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients or other resources (no-op if none)."""


class STTProvider(ABC):
    """Contract for speech-to-text backends."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier."""

    @abstractmethod
    async def transcribe(
        self, audio_bytes: bytes, language: str = "pt"
    ) -> str:
        """
        Transcribe raw audio bytes to plain text.

        ``language`` is an ISO 639-1 hint (e.g. ``pt``, ``en``).
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients or other resources (no-op if none)."""


class TTSProvider(ABC):
    """Contract for text-to-speech backends."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier."""

    @abstractmethod
    async def synthesize(
        self, text: str, voice_id: str | None = None
    ) -> bytes:
        """
        Synthesize speech audio from text.

        Returns raw audio bytes (typically MP3). ``voice_id`` meaning depends
        on the provider (ElevenLabs voice id, path to speaker WAV for Coqui, etc.).
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients or other resources (no-op if none)."""
