"""Application configuration."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "autonomous-agent"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24  # 24h

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/autonomous_agent"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"

    # Embeddings (1536 OpenAI text-embedding-3-small, 768 Ollama nomic-embed-text)
    embedding_dimensions: int = 1536

    # Twilio (WhatsApp + Voz)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None

    # Telegram
    telegram_bot_token: Optional[str] = None

    # ElevenLabs (TTS)
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (padrão)

    # D-ID (Avatar)
    did_api_key: Optional[str] = None

    # Provider selection (commercial vs open source)
    llm_provider: str = "openai"  # openai | ollama
    stt_provider: str = "openai"  # openai | faster_whisper
    tts_provider: str = "elevenlabs"  # elevenlabs | coqui
    avatar_provider: str = "did"  # did | sadtalker

    # Ollama (LLM_PROVIDER=ollama)
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1"

    # faster-whisper (STT_PROVIDER=faster_whisper)
    whisper_base_url: str = "http://faster-whisper:8001"
    whisper_model: str = "large-v3"

    # Coqui XTTS-v2 (TTS_PROVIDER=coqui)
    coqui_base_url: str = "http://coqui-tts:8002"
    coqui_voice_sample: Optional[str] = None

    # SadTalker (AVATAR_PROVIDER=sadtalker)
    sadtalker_base_url: str = "http://sadtalker:8003"

    # Frontend
    frontend_url: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


settings = Settings()