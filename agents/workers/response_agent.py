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
- Você está numa LIGAÇÃO TELEFÔNICA. Tom natural e amigável — como um atendente real ao telefone.
- Responda em NO MÁXIMO 2 frases curtas (até ~20 palavras no total). Vá direto ao ponto.
- Não repita o que o cliente disse. Não se apresente mais de uma vez na mesma ligação.
- NUNCA use listas, numeração, bullets ou vários tópicos — resuma em uma frase e ofereça detalhar se quiser.
- NUNCA escreva parágrafos longos, aulas ou explicações extensas — o cliente está ao telefone.
- Use linguagem falada; evite markdown, emojis e símbolos especiais.
- Se precisar de mais informação, faça UMA pergunta curta por vez.
- O encerramento da ligação é controlado pelo sistema; não invente despedidas longas."""

VOICE_OPENING_MISHEARD_PROMPT = """Primeiro turno desta ligação (ainda não houve conversa).
O transcript pode parecer despedida por erro de reconhecimento de voz — trate como ABERTURA:
cumprimente e ofereça ajuda. Não se despeça neste turno."""

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
    Garante fim de frase completo para TTS (evita truncamento no meio pelo max_tokens).

    Corta de volta até o último '.', '!' ou '?'. Remove fragmentos de lista soltos no fim.
    """
    cleaned = _strip_orphan_list_fragments((text or "").strip())
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".!?":
        return cleaned

    last_idx = max(cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?"))
    if last_idx == -1:
        return cleaned

    return _strip_orphan_list_fragments(cleaned[: last_idx + 1].strip())


_ORPHAN_LIST_TAIL_RE = re.compile(
    r"(?:\n|\s)+(?:\d+[\.\)]|[-*•])\s*$",
    re.MULTILINE,
)
_LIST_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s+\S", re.MULTILINE)
_ORPHAN_LIST_CONNECTOR_RES = (
    re.compile(r",\s*incluindo\.?$", re.IGNORECASE),
    re.compile(r",\s*como\.?$", re.IGNORECASE),
    re.compile(r",\s*tais como\.?$", re.IGNORECASE),
    re.compile(r",\s*entre eles\.?$", re.IGNORECASE),
    re.compile(r",\s*entre elas\.?$", re.IGNORECASE),
    re.compile(r",\s*como por exemplo\.?$", re.IGNORECASE),
    re.compile(r":\s*$"),
    re.compile(r",\s*$"),
)


def _resolve_list_detail_offer() -> str:
    offer = (settings.voice_list_detail_offer or "").strip()
    return offer or "Quer que eu detalhe alguma?"


def _normalize_opening_sentence(text: str) -> str:
    opening = (text or "").strip()
    if not opening:
        return opening
    if opening[-1] not in ".!?":
        opening = f"{opening}."
    return opening


def response_contains_spoken_list(text: str) -> bool:
    """True when the reply looks like a multi-line or bulleted list (bad for TTS)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if _LIST_BULLET_LINE_RE.search(cleaned):
        return True
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) >= 3:
        return True
    if ":" in cleaned:
        _, tail = cleaned.split(":", 1)
        tail_lines = [line.strip() for line in tail.splitlines() if line.strip()]
        if len(tail_lines) >= 2:
            return True
        if _LIST_BULLET_LINE_RE.search(tail):
            return True
    return False


def _clean_orphan_list_connectors(text: str) -> str:
    """Remove conectores de lista órfãos no fim (ex: ', incluindo.' sem itens)."""
    original = (text or "").strip()
    cleaned = original
    if not cleaned:
        return cleaned
    while True:
        trimmed = cleaned
        for pattern in _ORPHAN_LIST_CONNECTOR_RES:
            trimmed = pattern.sub("", trimmed).strip()
        if trimmed == cleaned:
            break
        cleaned = trimmed
    if cleaned and cleaned != original:
        cleaned = _normalize_opening_sentence(cleaned)
    return cleaned


def _append_list_detail_offer(base: str) -> str:
    opening = (base or "").strip()
    if not opening:
        return _resolve_list_detail_offer()
    return f"{opening} {_resolve_list_detail_offer()}".strip()


def _collapse_list_base_for_telephony(text: str) -> str:
    """Extrai a frase de abertura (sem lista) com conectores órfãos removidos."""
    cleaned = (text or "").strip()
    if not cleaned or not response_contains_spoken_list(cleaned):
        return cleaned

    if ":" in cleaned:
        opening = cleaned.split(":", 1)[0].strip()
    else:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        opening = lines[0] if lines else cleaned

    opening = _clean_orphan_list_connectors(opening)
    return _normalize_opening_sentence(opening)


def collapse_voice_list_for_telephony(text: str) -> str:
    """
    Replace list-style replies with a short opening line + detail offer.

    Example: "Oferecemos cursos, incluindo:\\n Excel\\n BI" ->
    "Oferecemos cursos em várias áreas. Quer que eu detalhe alguma?"
    """
    cleaned = (text or "").strip()
    if not cleaned or not response_contains_spoken_list(cleaned):
        return cleaned

    base = _collapse_list_base_for_telephony(cleaned)
    return _append_list_detail_offer(base)


def _strip_orphan_list_fragments(text: str) -> str:
    """Remove bullets/numeracao orfaos no fim (ex: '\\n2.' sozinho)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    while True:
        trimmed = _ORPHAN_LIST_TAIL_RE.sub("", cleaned).strip()
        trimmed = re.sub(r"\n\d+\.\s*$", "", trimmed).strip()
        if trimmed == cleaned:
            return cleaned
        cleaned = trimmed


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


def cap_voice_response_at_sentence_boundary(
    text: str,
    max_chars: int,
    *,
    hard_max_chars: int | None = None,
) -> str:
    """
    Rede de segurança pós-LLM: limita tamanho sem cortar no meio de palavra.

    1. Corta na última frase completa dentro do cap.
    2. Se não houver, permite folga (hard_max) para completar a frase.
    3. Senão, corta na última palavra completa e fecha com '.'.
    """
    cleaned = (text or "").strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned

    hard = hard_max_chars if hard_max_chars is not None else max_chars + 30
    soft_window = cleaned[:max_chars]

    last_punct = max(
        soft_window.rfind("."),
        soft_window.rfind("!"),
        soft_window.rfind("?"),
    )
    if last_punct > 0:
        return cleaned[: last_punct + 1].strip()

    if len(cleaned) > max_chars:
        hard_window = cleaned[:hard]
        last_punct = max(
            hard_window.rfind("."),
            hard_window.rfind("!"),
            hard_window.rfind("?"),
        )
        if last_punct >= max_chars:
            return cleaned[: last_punct + 1].strip()

    last_space = soft_window.rfind(" ")
    if last_space > 0:
        chunk = cleaned[:last_space].strip()
        if chunk and chunk[-1] not in ".!?":
            chunk = f"{chunk}."
        return chunk

    chunk = cleaned[:max_chars].strip()
    if chunk and chunk[-1] not in ".!?":
        chunk = f"{chunk}."
    return chunk


def _voice_cap_hard_limit(max_chars: int) -> int:
    overflow = int(getattr(settings, "voice_max_response_chars_overflow", 30) or 0)
    return max_chars + max(0, overflow)


def sanitize_voice_response_for_telephony(text: str) -> str:
    """
    Sanitiza resposta de voz para TTS.

    Remove markdown, colapsa listas (cap na base + oferta isenta), corta com segurança
    e descarta cauda truncada pelo max_tokens (nunca envia texto malformado).
    """
    cleaned = _strip_markdown_for_tts(text)
    cleaned = _strip_orphan_list_fragments(cleaned)
    cleaned = _clean_orphan_list_connectors(cleaned)
    max_chars = int(settings.voice_max_response_chars or 0)
    hard_max = _voice_cap_hard_limit(max_chars) if max_chars > 0 else 0

    if response_contains_spoken_list(cleaned):
        base = _collapse_list_base_for_telephony(cleaned)
        if max_chars > 0:
            base = cap_voice_response_at_sentence_boundary(
                base,
                max_chars,
                hard_max_chars=hard_max,
            )
        cleaned = _append_list_detail_offer(base)
    elif max_chars > 0:
        cleaned = cap_voice_response_at_sentence_boundary(
            cleaned,
            max_chars,
            hard_max_chars=hard_max,
        )

    cleaned = trim_voice_response_to_complete_sentence(cleaned)
    return _strip_orphan_list_fragments(cleaned)


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
    voice_opening_turn: bool = False,
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
        if voice_opening_turn:
            messages.append({"role": "system", "content": VOICE_OPENING_MISHEARD_PROMPT})
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
    voice_opening_turn: bool = False,
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
        voice_opening_turn=voice_opening_turn,
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
