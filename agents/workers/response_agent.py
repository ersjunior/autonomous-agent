"""Response generation worker."""

import logging

from agents.provider_factory import ProviderFactory
from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT, settings

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = DEFAULT_AGENT_SYSTEM_PROMPT

# B-1: instruções operacionais do modo RECEPTIVE (complementa agent_personality/description).
RECEPTIVE_BEHAVIOR_PROMPT = """Modo RECEPTIVO — como conduzir o atendimento:
- Responda dúvidas com clareza, usando o histórico imediato e as memórias de longo prazo (RAG)
  quando disponíveis. Não invente fatos, preços ou políticas que não estejam no contexto.
- Qualifique quando fizer sentido: entenda a necessidade do lead com perguntas naturais e
  pertinentes, uma de cada vez, sem interrogatório. Se o lead demonstra interesse mas não
  detalha, faça uma pergunta por vez para entender melhor (ex.: o que busca, para quando, qual canal prefere).
- Mantenha tom acolhedor e profissional; conversa fluida, não roteiro rígido de script.
- Desvio leve fora do escopo (piada, humor, curiosidade, opinião, política, assunto pessoal
  sem relação com o negócio): NÃO escale para humano — recuse educadamente e redirecione
  para produtos, serviços ou dúvidas do atendimento.
- Escale para atendente humano apenas quando necessário: reclamação grave, pedido explícito
  de atendente humano ou sinal claro de escalonamento — reconheça e indique a transferência."""

# Inbound/outbound de voz (telefonia): respostas curtas para TTS e timeout da Twilio.
VOICE_BEHAVIOR_PROMPT = """Modo VOZ (telefone) — como falar com o cliente:
- Você está em uma LIGAÇÃO TELEFÔNICA; responda de forma CURTA e objetiva (no máximo 3 a 4 frases).
- Use linguagem falada natural, direta ao ponto; evite listas, markdown, emojis e parágrafos longos.
- Prefira frases curtas que soem bem quando lidas em voz alta; vá direto ao que o cliente precisa."""


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
    agent_personality: str | None = None,
    agent_mode: str | None = None,
) -> list[dict]:
    """
    Monta mensagens para o LLM de resposta (exposto para testes e generate_response).

    Ordem dos blocos de sistema:
      1. prompt global → 2. personality → 3. RECEPTIVE (se aplicável)
      4. VOZ (se canal voice) → 5. KB institucional → 6. memória de contato
      7. canal/intent/entidades → 8. histórico → 9. mensagem atual
    """
    context = (
        f"Canal: {channel}\n"
        f"Intenção detectada: {intent}\n"
        f"Entidades: {entities}"
    )

    messages: list[dict] = [{"role": "system", "content": _resolve_system_prompt()}]

    if agent_personality:
        messages.append({"role": "system", "content": agent_personality})

    mode = (agent_mode or "").upper()
    if mode == "RECEPTIVE":
        messages.append({"role": "system", "content": RECEPTIVE_BEHAVIOR_PROMPT})

    if (channel or "").lower() == "voice":
        messages.append({"role": "system", "content": VOICE_BEHAVIOR_PROMPT})

    kb_block = format_kb_context_block(kb_chunks or [])
    if kb_block:
        messages.append({"role": "system", "content": kb_block})

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
    agent_personality: str | None = None,
    agent_mode: str | None = None,
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
        agent_personality=agent_personality,
        agent_mode=agent_mode,
    )

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
        text = trim_voice_response_to_complete_sentence(text)

    return text
