"""Response generation worker."""

import logging
import re

from agents.identity import format_institutional_identity_block
from agents.provider_factory import ProviderFactory
from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, settings

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = DEFAULT_AGENT_SYSTEM_PROMPT

# B-1: instruções operacionais do modo RECEPTIVE (complementa agent_personality/description).
RECEPTIVE_BEHAVIOR_PROMPT = """Modo RECEPTIVO — como conduzir o atendimento:
- Converse de forma natural e simpática, como alguém que conhece bem o assunto e gosta de ajudar.
- Responda dúvidas com clareza, usando o histórico imediato, a base de conhecimento e as memórias de longo prazo (RAG)
  quando disponíveis. Não invente fatos, preços ou políticas que não estejam no contexto.
- Qualifique quando fizer sentido: entenda a necessidade do lead com perguntas naturais e
  pertinentes, uma de cada vez, sem interrogatório.
- Mantenha tom acolhedor e acessível; conversa fluida, não roteiro rígido de script.
- Desvio leve fora do escopo (piada, humor, curiosidade, opinião, política, assunto pessoal
  sem relação com o negócio): NÃO escale para humano — recuse educadamente e redirecione
  para produtos, serviços ou dúvidas do atendimento.
- Escale para atendente humano apenas quando necessário: reclamação grave, pedido explícito
  de atendente humano ou sinal claro de escalonamento — reconheça e indique a transferência."""

VOICE_BEHAVIOR_PROMPT = """Modo VOZ (telefone) — como falar com o cliente:
- Você está numa LIGAÇÃO TELEFÔNICA. Tom natural e amigável — como alguém simpático numa conversa real. Nem telegráfico, nem monólogos.
- Em ligações, seja BREVE: responda em 1 a 3 frases curtas. Vá direto ao ponto. Se o cliente quiser mais detalhes, ele vai perguntar.
- NUNCA liste vários itens de uma vez numa ligação — resuma e ofereça detalhar se quiser saber mais.
- Use o histórico, a base de conhecimento e as memórias (RAG) quando disponíveis — não invente o que não estiver no contexto.
- Use linguagem falada; evite markdown, emojis, listas longas ou parágrafos densos.
- Se precisar de mais informação, faça perguntas claras e naturais (preferencialmente uma de cada vez).
- O encerramento da ligação é controlado pelo sistema; responda ao cliente e não invente despedidas longas.
- Só se despeça quando o cliente indicar claramente que não precisa de mais nada. Se você estiver fazendo uma pergunta, a conversa continua — não encerre nesse turno."""

TEXT_BEHAVIOR_PROMPT = """Modo TEXTO (WhatsApp/Telegram) — como escrever para o cliente:
- Por mensagem, pode desenvolver mais quando ajudar à clareza — organize em parágrafos curtos se facilitar a leitura.
- Mantenha tom amigável e conversacional; evite respostas secas ou telegráficas quando o assunto pede contexto.
- Emojis só se combinar com o tom da marca; prefira clareza à quantidade de texto.
- Se a resposta for longa, priorize o que o cliente perguntou primeiro."""


def _resolve_system_prompt() -> str:
    prompt = (settings.agent_system_prompt or "").strip()
    return prompt if prompt else DEFAULT_SYSTEM_PROMPT


def _resolve_max_tokens(channel: str) -> int | None:
    """Limite de tokens para o LLM — cap dedicado em voice, global nos demais canais."""
    ch = (channel or "").lower()
    if ch == "voice":
        cap = settings.voice_response_max_tokens
        return cap if cap > 0 else None
    cap = settings.response_max_tokens
    return cap if cap > 0 else None


def trim_voice_response_to_complete_sentence(text: str) -> str:
    """
    Garante fim de frase completo para TTS (evita truncamento no meio da palavra/frase).

    Se não houver pontuação de fim de frase, mantém o texto original.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".!?":
        return cleaned

    last_idx = max(cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?"))
    if last_idx == -1:
        return cleaned

    return cleaned[: last_idx + 1].strip()


def _strip_markdown_for_tts(text: str) -> str:
    """Remove marcações não faláveis (markdown) antes do TTS."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def cap_voice_response_at_sentence_boundary(text: str, max_chars: int) -> str:
    """
    Rede de segurança pós-LLM: limita tamanho cortando na última frase completa.

    Evita respostas extremas (500+ chars) se o LLM ignorar prompt e token cap.
    """
    cleaned = (text or "").strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned

    window = cleaned[:max_chars]
    last_idx = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if last_idx > 0:
        return cleaned[: last_idx + 1].strip()

    return trim_voice_response_to_complete_sentence(window)


def sanitize_voice_response_for_telephony(text: str) -> str:
    """
    Sanitiza resposta de voz para TTS.

    Remove markdown, aplica cap generoso em fronteira de frase (se configurado)
    e fecha frase incompleta quando o LLM para no meio por limite de tokens.
    """
    cleaned = _strip_markdown_for_tts(text)
    max_chars = int(settings.voice_max_response_chars or 0)
    if max_chars > 0:
        cleaned = cap_voice_response_at_sentence_boundary(cleaned, max_chars)
    return trim_voice_response_to_complete_sentence(cleaned)


def _history_to_messages(history: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for item in history:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in ("user", "human", "customer"):
            messages.append({"role": "user", "content": content})
        elif role in ("assistant", "ai", "agent"):
            messages.append({"role": "assistant", "content": content})
    return messages


def _append_current_user_message(messages: list[dict], message: str) -> None:
    """Append the current user turn unless it is already the last user message."""
    if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == message:
        return
    messages.append({"role": "user", "content": message})


def format_kb_context_block(kb_chunks: list[dict]) -> str | None:
    """Bloco institucional — precede a memória de contato no prompt."""
    if not kb_chunks:
        return None

    lines = [
        "Base de conhecimento da empresa (informações institucionais — use para responder "
        "com precisão sobre horários, políticas, preços e produtos; não invente além disto):",
    ]
    for item in kb_chunks:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        title = (item.get("document_title") or "Documento").strip()
        sim = item.get("similarity")
        suffix = f" [similaridade {sim:.2f}]" if isinstance(sim, (int, float)) else ""
        lines.append(f"- [{title}]{suffix}: {content}")

    if len(lines) <= 1:
        return None
    return "\n".join(lines)


def format_rag_context_block(rag_memories: list[dict]) -> str | None:
    """Monta bloco de sistema com interações antigas (não confundir com histórico Redis)."""
    if not rag_memories:
        return None

    lines = [
        "Conversas anteriores relevantes com este contato (memória de longo prazo, "
        "outras sessões — não é o histórico imediato da conversa atual):",
    ]
    for item in rag_memories:
        past_msg = (item.get("message") or "").strip()
        past_resp = (item.get("response") or "").strip()
        if not past_msg and not past_resp:
            continue
        sim = item.get("similarity")
        suffix = f" [similaridade {sim:.2f}]" if isinstance(sim, (int, float)) else ""
        lines.append(f"- Cliente: {past_msg} → Atendente: {past_resp}{suffix}")

    if len(lines) <= 1:
        return None
    return "\n".join(lines)


def build_response_messages(
    message: str,
    intent: str,
    entities: dict,
    history: list[dict],
    channel: str,
    *,
    rag_memories: list[dict] | None = None,
    kb_chunks: list[dict] | None = None,
    booking_context: str | None = None,
    agent_personality: str | None = None,
    agent_mode: str | None = None,
    agent_config: dict | None = None,
) -> list[dict]:
    """
    Monta mensagens para o LLM de resposta (exposto para testes e generate_response).

    Ordem dos blocos de sistema:
      1. prompt global → 2. identidade institucional (se config.identity)
      3. personality → 4. RECEPTIVE (se aplicável) → 5. VOZ ou TEXTO (por canal)
      6. KB institucional → 7. agendamento (se houver) → 8. memória de contato
      9. canal/intent/entidades → 10. histórico → 11. mensagem atual
    """
    context = (
        f"Canal: {channel}\n"
        f"Intenção detectada: {intent}\n"
        f"Entidades: {entities}"
    )

    messages: list[dict] = [{"role": "system", "content": _resolve_system_prompt()}]

    identity_block = format_institutional_identity_block(agent_config)
    identity_raw = (agent_config or {}).get("identity") if isinstance(agent_config, dict) else None
    company = None
    if isinstance(identity_raw, dict):
        company = (identity_raw.get("display_name") or identity_raw.get("company_name") or "").strip() or None
    logger.info(
        "Identity prompt diagnostic channel=%s agent_config=%s identity_keys=%s block=%s company=%s",
        channel,
        "present" if agent_config else "absent",
        list(identity_raw.keys()) if isinstance(identity_raw, dict) else None,
        "present" if identity_block else "absent",
        company or "-",
    )
    if identity_block:
        messages.append({"role": "system", "content": identity_block})

    if agent_personality:
        messages.append({"role": "system", "content": agent_personality})

    mode = (agent_mode or "").upper()
    if mode == "RECEPTIVE":
        messages.append({"role": "system", "content": RECEPTIVE_BEHAVIOR_PROMPT})

    ch = (channel or "").lower()
    if ch == "voice":
        messages.append({"role": "system", "content": VOICE_BEHAVIOR_PROMPT})
    elif ch in ("whatsapp", "telegram"):
        messages.append({"role": "system", "content": TEXT_BEHAVIOR_PROMPT})

    kb_block = format_kb_context_block(kb_chunks or [])
    if kb_block:
        messages.append({"role": "system", "content": kb_block})

    if booking_context:
        messages.append({"role": "system", "content": booking_context})

    # Voice: each call is self-contained — past conversation RAG is omitted (KB only).
    if ch != "voice":
        rag_block = format_rag_context_block(rag_memories or [])
        if rag_block:
            messages.append({"role": "system", "content": rag_block})

    messages.append({"role": "system", "content": context})
    messages.extend(_history_to_messages(history))
    _append_current_user_message(messages, message)
    return messages


async def generate_response(
    message: str,
    intent: str,
    entities: dict,
    history: list[dict],
    channel: str,
    rag_memories: list[dict] | None = None,
    kb_chunks: list[dict] | None = None,
    booking_context: str | None = None,
    agent_personality: str | None = None,
    agent_mode: str | None = None,
    agent_config: dict | None = None,
) -> str:
    llm = ProviderFactory.get_llm()

    messages = build_response_messages(
        message,
        intent,
        entities,
        history,
        channel,
        rag_memories=rag_memories,
        kb_chunks=kb_chunks,
        booking_context=booking_context,
        agent_personality=agent_personality,
        agent_mode=agent_mode,
        agent_config=agent_config,
    )

    if format_institutional_identity_block(agent_config):
        logger.debug("Institutional identity block injected for channel=%s", channel)

    if agent_mode and agent_mode.upper() == "RECEPTIVE":
        logger.debug(
            "RECEPTIVE behavior block injected for channel=%s (messages=%s)",
            channel,
            len(messages),
        )

    if (channel or "").lower() == "voice":
        logger.debug(
            "VOICE behavior block injected for channel=%s (messages=%s)",
            channel,
            len(messages),
        )

    kb_block = format_kb_context_block(kb_chunks or [])
    if kb_block:
        logger.debug("KB context injected (%s chunks)", len(kb_chunks or []))

    if booking_context:
        logger.debug("Booking context injected for channel=%s", channel)

    if (channel or "").lower() != "voice":
        rag_block = format_rag_context_block(rag_memories or [])
        if rag_block:
            logger.debug("RAG memory context injected (%s memories)", len(rag_memories or []))

    max_tokens = _resolve_max_tokens(channel)
    if (channel or "").lower() == "voice" and max_tokens:
        logger.debug("Voice response max_tokens=%s", max_tokens)

    result = await llm.complete(
        messages,
        temperature=settings.response_temperature,
        max_tokens=max_tokens,
    )
    if not isinstance(result, str):
        logger.warning("Unexpected content type: %s", type(result))
    text = result if isinstance(result, str) else str(result)

    if (channel or "").lower() == "voice":
        text = sanitize_voice_response_for_telephony(text)

    return text
