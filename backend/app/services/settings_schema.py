"""Whitelist and metadata for UI-managed application settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, DEFAULT_VOICE_INBOUND_GREETING

SettingCategory = Literal["llm", "stt", "tts", "system", "agent"]
SettingFieldType = Literal["string", "enum", "secret", "url", "number", "textarea"]
NumericValueType = Literal["int", "float"]

AGENT_SYSTEM_PROMPT_MAX_LENGTH = 4000


@dataclass(frozen=True)
class SettingFieldSchema:
    key: str
    label: str
    category: SettingCategory
    field_type: SettingFieldType
    options: tuple[str, ...] = ()
    is_secret: bool = False
    read_only: bool = False
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    max_length: int | None = None
    default_value: str | None = None
    value_type: NumericValueType | None = None


MANAGED_SETTINGS: tuple[SettingFieldSchema, ...] = (
    # LLM
    SettingFieldSchema(
        key="llm_provider",
        label="Provedor LLM",
        category="llm",
        field_type="enum",
        options=("openai", "ollama"),
    ),
    SettingFieldSchema(
        key="openai_model",
        label="Modelo OpenAI",
        category="llm",
        field_type="string",
    ),
    SettingFieldSchema(
        key="openai_api_key",
        label="Chave API OpenAI",
        category="llm",
        field_type="secret",
        is_secret=True,
    ),
    SettingFieldSchema(
        key="ollama_base_url",
        label="URL base Ollama",
        category="llm",
        field_type="url",
    ),
    SettingFieldSchema(
        key="ollama_model",
        label="Modelo Ollama",
        category="llm",
        field_type="string",
    ),
    # STT
    SettingFieldSchema(
        key="stt_provider",
        label="Provedor STT",
        category="stt",
        field_type="enum",
        options=("openai", "faster_whisper"),
    ),
    SettingFieldSchema(
        key="whisper_base_url",
        label="URL faster-whisper",
        category="stt",
        field_type="url",
    ),
    SettingFieldSchema(
        key="whisper_model",
        label="Modelo Whisper",
        category="stt",
        field_type="string",
    ),
    # TTS
    SettingFieldSchema(
        key="tts_provider",
        label="Provedor TTS",
        category="tts",
        field_type="enum",
        options=("elevenlabs", "coqui"),
    ),
    SettingFieldSchema(
        key="elevenlabs_api_key",
        label="Chave API ElevenLabs",
        category="tts",
        field_type="secret",
        is_secret=True,
    ),
    SettingFieldSchema(
        key="elevenlabs_voice_id",
        label="Voice ID ElevenLabs",
        category="tts",
        field_type="string",
    ),
    SettingFieldSchema(
        key="coqui_base_url",
        label="URL Coqui TTS",
        category="tts",
        field_type="url",
    ),
    SettingFieldSchema(
        key="coqui_voice_sample",
        label="Amostra de voz Coqui (path)",
        category="tts",
        field_type="string",
    ),
    # Comportamento do agente
    SettingFieldSchema(
        key="intent_temperature",
        label="Temperatura (classificação de intenção)",
        category="agent",
        field_type="number",
        value_type="float",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        default_value="0",
    ),
    SettingFieldSchema(
        key="response_temperature",
        label="Temperatura (geração de resposta)",
        category="agent",
        field_type="number",
        value_type="float",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        default_value="0.3",
    ),
    SettingFieldSchema(
        key="agent_system_prompt",
        label="Prompt do sistema (personalidade do agente)",
        category="agent",
        field_type="textarea",
        max_length=AGENT_SYSTEM_PROMPT_MAX_LENGTH,
        default_value=DEFAULT_AGENT_SYSTEM_PROMPT,
    ),
    SettingFieldSchema(
        key="rag_top_k",
        label="RAG: nº de memórias similares",
        category="agent",
        field_type="number",
        value_type="int",
        min_value=0,
        max_value=20,
        step=1,
        default_value="5",
    ),
    SettingFieldSchema(
        key="rag_similarity_threshold",
        label="RAG: limiar de similaridade",
        category="agent",
        field_type="number",
        value_type="float",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        default_value="0",
    ),
    SettingFieldSchema(
        key="response_max_tokens",
        label="Limite de tokens da resposta (0 = sem limite)",
        category="agent",
        field_type="number",
        value_type="int",
        min_value=0,
        max_value=4096,
        step=64,
        default_value="1024",
    ),
    SettingFieldSchema(
        key="voice_response_max_tokens",
        label="Teto de tokens da resposta em voz (0 = sem limite; padrão ~64, 1–3 frases)",
        category="agent",
        field_type="number",
        value_type="int",
        min_value=0,
        max_value=2048,
        step=64,
        default_value="64",
    ),
    SettingFieldSchema(
        key="human_handoff_enabled",
        label="Handoff humano ativo (notificar operador no escalonamento)",
        category="agent",
        field_type="enum",
        options=("true", "false"),
        default_value="true",
    ),
    SettingFieldSchema(
        key="human_handoff_whatsapp",
        label="WhatsApp do atendente humano (E.164 ou DDD+número)",
        category="agent",
        field_type="string",
        default_value="",
    ),
    SettingFieldSchema(
        key="voice_inbound_greeting",
        label="Saudação inicial do atendimento por voz",
        category="agent",
        field_type="string",
        default_value=DEFAULT_VOICE_INBOUND_GREETING,
    ),
    # Read-only (env / migration)
    SettingFieldSchema(
        key="embedding_dimensions",
        label="Dimensões de embedding",
        category="system",
        field_type="string",
        read_only=True,
    ),
)

MANAGED_KEYS: frozenset[str] = frozenset(s.key for s in MANAGED_SETTINGS)
EDITABLE_KEYS: frozenset[str] = frozenset(
    s.key for s in MANAGED_SETTINGS if not s.read_only
)
SCHEMA_BY_KEY: dict[str, SettingFieldSchema] = {s.key: s for s in MANAGED_SETTINGS}

CATEGORY_LABELS: dict[SettingCategory, str] = {
    "llm": "LLM",
    "stt": "STT (Speech-to-Text)",
    "tts": "TTS (Text-to-Speech)",
    "system": "Sistema",
    "agent": "Comportamento do agente",
}
