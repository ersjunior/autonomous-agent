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

    # Frontend
    frontend_url: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


settings = Settings()