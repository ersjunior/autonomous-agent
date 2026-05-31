"""Response generation worker."""

import logging

from agents.provider_factory import ProviderFactory

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um atendente profissional, empático e objetivo.
Responda de forma clara e útil, adaptando o tom ao canal de atendimento.
Use o contexto da intenção e das entidades extraídas para personalizar a resposta.
Não invente informações que não estejam no histórico ou no contexto fornecido."""


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


async def generate_response(
    intent: str,
    entities: dict,
    history: list[dict],
    channel: str,
) -> str:
    llm = ProviderFactory.get_llm()

    context = (
        f"Canal: {channel}\n"
        f"Intenção detectada: {intent}\n"
        f"Entidades: {entities}"
    )

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context},
        *_history_to_messages(history),
    ]

    result = await llm.complete(messages, temperature=0.7)
    if not isinstance(result, str):
        logger.warning("Unexpected content type: %s", type(result))
    return result if isinstance(result, str) else str(result)
