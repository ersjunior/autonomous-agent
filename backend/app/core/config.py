"""Application configuration."""

from pathlib import Path

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
    # PSTN dedicado à voz (opcional; senão usa twilio_phone_number sem prefixo whatsapp:)
    twilio_voice_number: Optional[str] = None

    # URL pública do backend (ngrok, domínio, IP, Cloudflare Tunnel) — sem barra final
    public_base_url: Optional[str] = None

    # TUN-1 — Cloudflare Tunnel (docker-compose serviço cloudflared)
    # temporary: URL lida de tunnel_url_file (quick tunnel *.trycloudflare.com)
    # named: PUBLIC_BASE_URL fixa no .env + CLOUDFLARE_TUNNEL_TOKEN no serviço cloudflared
    tunnel_mode: str = "temporary"  # temporary | named
    tunnel_url_file: str = "/shared/tunnel_url.txt"

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
    avatar_provider: str = "sadtalker"  # sadtalker | did

    # Ollama (LLM_PROVIDER=ollama)
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1"

    # faster-whisper (STT_PROVIDER=faster_whisper)
    whisper_base_url: str = "http://faster-whisper:8001"
    whisper_model: str = "large-v3"

    # Coqui XTTS-v2 (TTS_PROVIDER=coqui)
    coqui_base_url: str = "http://coqui-tts:8002"
    coqui_voice_sample: Optional[str] = None
    # Volume compartilhado com coqui-tts (reference.wav) — não editável via UI de providers
    coqui_voices_root: str = "/voices"

    # MP3s de chamadas outbound (volume Docker voice_audio)
    voice_audio_root: str = "/workspace/voice_audio"

    # SadTalker (AVATAR_PROVIDER=sadtalker)
    sadtalker_base_url: str = "http://sadtalker:8003"
    # MP4 gerados pelo SadTalker (volume Docker avatar_video)
    avatar_video_root: str = "/workspace/avatar_video"
    avatars_root: str = "/avatars"
    avatar_default_image: str = "default.png"

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Motor de acionamento — fuso para janela de horário (camada B+)
    activation_timezone: str = "America/Sao_Paulo"

    # Lead interaction status sweep (worker): acionado sem resposta → nao_atendido
    status_timeout_hours: int = 48

    # Janela de conversa ativa outbound (inbound continua com o agente ACTIVE):
    # encerra se (now - data_ultimo_contato) > N horas. Separado de status_timeout_hours.
    active_conversation_timeout_hours: int = 24

    # Camada D — TTL de slots Redis (sem callback Twilio; estimativa + rede de segurança)
    # Voz/vídeo: duração estimada da chamada até o holder expirar e liberar o slot.
    call_slot_ttl_seconds: int = 300
    # WhatsApp/Telegram: TTL de segurança do holder; liberação principal ao encerrar conversa.
    chat_slot_ttl_seconds: int = 24 * 3600  # alinhado a active_conversation_timeout_hours (24h)

    # R-A / R-C — capacidade global ponderada (ativo + receptivo compartilham teto)
    max_weighted_capacity: int = 50  # legado; usado se override=0 e estimativa falhar
    max_weighted_capacity_override: int = 0  # >0 força teto manual; 0 = derivado do hardware
    channel_weight_whatsapp: int = 1
    channel_weight_telegram: int = 1
    channel_weight_voice: int = 3
    channel_weight_video: int = 4

    # R-C — estimativa de capacidade (unidades abstratas de recurso por canal simultâneo)
    channel_cost_whatsapp: float = 1.0
    channel_cost_telegram: float = 1.0
    channel_cost_voice: float = 3.0
    channel_cost_video: float = 5.0
    capacity_cpu_units_per_core: float = 10.0
    capacity_mb_per_unit: float = 512.0
    gpu_capacity_boost: float = 1.15
    default_aht_seconds: int = 180
    capacity_history_days: int = 7
    erlang_target_service_level: float = 0.80

    # R-A — fila receptiva
    receptive_queue_payload_ttl_seconds: int = 24 * 3600
    receptive_queue_beat_seconds: int = 30

    # R-B — métricas de fila / abandono (voz) / SLA
    service_level_target_seconds: int = 20
    queue_abandon_timeout_seconds: int = 60

    # B-2 — modo humano após escalonamento (Redis TTL + mensagem ocasional)
    # Legado: alias do queue TTL curto; preferir human_handoff_queue_ttl_seconds (H-2).
    human_mode_ttl_seconds: int = 1800
    human_mode_notify_interval_seconds: int = 300  # 5min — throttle msg de espera

    # H-2 — ciclo de finalização do handoff humano
    human_handoff_queue_ttl_seconds: int = 1800  # 30min sem assumir → devolve ao bot
    human_handoff_finalize_ttl_seconds: int = 14400  # 4h após assumir → auto NEG:ABANDONO
    human_handoff_sweep_seconds: int = 60  # intervalo do Beat sweep_human_handoff_timeouts

    # H-1 — handoff humano: notificação do operador + link wa.me ao lead no escalonamento
    human_handoff_whatsapp: str = ""  # E.164 do atendente; vazio = desabilitado
    human_handoff_enabled: bool = True  # requer número preenchido para ativar na prática

    # KB-1 — base de conhecimento documental
    kb_uploads_root: str = "/workspace/kb_uploads"
    kb_chunk_size: int = 512  # tokens aproximados por chunk
    kb_chunk_overlap: int = 64  # tokens de overlap entre chunks
    kb_max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    def resolved_channel_weights(self) -> dict[str, int]:
        from app.core.activation_defaults import DEFAULT_CHANNEL_WEIGHTS

        base = dict(DEFAULT_CHANNEL_WEIGHTS)
        base["whatsapp"] = self.channel_weight_whatsapp
        base["telegram"] = self.channel_weight_telegram
        base["voice"] = self.channel_weight_voice
        base["video"] = self.channel_weight_video
        return base

    # Comportamento do agente (gerenciável via UI / app_settings)
    intent_temperature: float = 0.0
    response_temperature: float = 0.7
    agent_system_prompt: str = (
        "Você é um atendente profissional, empático e objetivo.\n"
        "Responda de forma clara e útil, adaptando o tom ao canal de atendimento.\n"
        "Use o contexto da intenção e das entidades extraídas para personalizar a resposta.\n"
        "Não invente informações que não estejam no histórico ou no contexto fornecido."
    )
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.0
    # KB-2 — recuperação semântica na base documental (mais seletiva que memória de contato)
    kb_top_k: int = 0  # 0 = usa rag_top_k
    kb_similarity_threshold: float = 0.62
    response_max_tokens: int = 0

    def resolved_kb_top_k(self) -> int:
        return self.rag_top_k if self.kb_top_k <= 0 else self.kb_top_k

    def _read_tunnel_url_file(self) -> str | None:
        path = Path(self.tunnel_url_file)
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return raw.rstrip("/")

    def resolve_public_base_url(self) -> str | None:
        """
        Resolve PUBLIC_BASE_URL para Twilio (voz outbound, URLs no TwiML).

        Prioridade:
          1. ``public_base_url`` no .env (manual ou named) — sempre vence.
          2. ``tunnel_mode=temporary`` — lê ``tunnel_url_file`` (quick tunnel).
          3. Caso contrário, None.
        """
        env_url = (self.public_base_url or "").strip()
        if env_url:
            return env_url.rstrip("/")

        mode = (self.tunnel_mode or "temporary").strip().lower()
        if mode == "temporary":
            return self._read_tunnel_url_file()
        return None

    def require_public_base_url(self) -> str:
        """Base URL pública exigida para Twilio buscar TwiML de voz outbound."""
        url = self.resolve_public_base_url()
        if url:
            return url

        mode = (self.tunnel_mode or "temporary").strip().lower()
        if mode == "temporary":
            raise ValueError(
                "PUBLIC_BASE_URL indisponível — túnel temporário ainda não publicou a URL "
                f"em {self.tunnel_url_file}. Aguarde o serviço cloudflared subir."
            )
        raise ValueError(
            "PUBLIC_BASE_URL não configurada — necessária para Twilio "
            "(defina no .env em TUNNEL_MODE=named ou manual)."
        )

    def whatsapp_webhook_url(self) -> str | None:
        """URL para cadastrar no console Twilio (Messaging webhook)."""
        base = self.resolve_public_base_url()
        if not base:
            return None
        return f"{base}/api/v1/channels/webhooks/whatsapp"

    def resolve_twilio_pstn_number(self) -> str:
        """Número PSTN de origem (+55...), nunca com prefixo whatsapp:."""
        raw = (self.twilio_voice_number or self.twilio_phone_number or "").strip()
        if not raw:
            raise ValueError(
                "TWILIO_VOICE_NUMBER ou TWILIO_PHONE_NUMBER não configurado para discagem PSTN"
            )
        if raw.lower().startswith("whatsapp:"):
            return raw.split(":", 1)[1].strip()
        return raw

    class Config:
        env_file = ".env"


ACTIVATION_TIMEZONE = "America/Sao_Paulo"

settings = Settings()