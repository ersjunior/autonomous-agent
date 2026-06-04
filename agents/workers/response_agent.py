"""Response generation worker."""

import logging

from agents.provider_factory import ProviderFactory
from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """Você é um atendente profissional, empático e objetivo.
Responda de forma clara e útil, adaptando o tom ao canal de atendimento.
Use o contexto da intenção e das entidades extraídas para personalizar a resposta.
Não invente informações que não estejam no histórico ou no contexto fornecido."""


def _resolve_system_prompt() -> str:
    prompt = (settings.agent_system_prompt or "").strip()
    return prompt if prompt else DEFAULT_SYSTEM_PROMPT


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


async def generate_response(
    message: str,
    intent: str,
    entities: dict,
    history: list[dict],
    channel: str,
    rag_memories: list[dict] | None = None,
    agent_personality: str | None = None,
) -> str:
    llm = ProviderFactory.get_llm()

    context = (
        f"Canal: {channel}\n"
        f"Intenção detectada: {intent}\n"
        f"Entidades: {entities}"
    )

    messages: list[dict] = [
        {"role": "system", "content": _resolve_system_prompt()},
        {"role": "system", "content": context},
    ]
    if agent_personality:
        messages.insert(1, {"role": "system", "content": agent_personality})

    rag_block = format_rag_context_block(rag_memories or [])
    if rag_block:
        messages.append({"role": "system", "content": rag_block})
        logger.debug("RAG context injected (%s memories)", len(rag_memories or []))

    messages.extend(_history_to_messages(history))
    _append_current_user_message(messages, message)

    max_tokens = (
        settings.response_max_tokens if settings.response_max_tokens > 0 else None
    )
    result = await llm.complete(
        messages,
        temperature=settings.response_temperature,
        max_tokens=max_tokens,
    )
    if not isinstance(result, str):
        logger.warning("Unexpected content type: %s", type(result))
    return result if isinstance(result, str) else str(result)
