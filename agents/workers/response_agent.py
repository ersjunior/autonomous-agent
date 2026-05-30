"""Response generation worker."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um atendente profissional, empático e objetivo.
Responda de forma clara e útil, adaptando o tom ao canal de atendimento.
Use o contexto da intenção e das entidades extraídas para personalizar a resposta.
Não invente informações que não estejam no histórico ou no contexto fornecido."""


def _history_to_messages(history: list[dict]) -> list[HumanMessage | AIMessage]:
    messages: list[HumanMessage | AIMessage] = []
    for item in history:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in ("user", "human", "customer"):
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai", "agent"):
            messages.append(AIMessage(content=content))
    return messages


async def generate_response(
    intent: str,
    entities: dict,
    history: list[dict],
    channel: str,
) -> str:
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.7,
    )

    context = (
        f"Canal: {channel}\n"
        f"Intenção detectada: {intent}\n"
        f"Entidades: {entities}"
    )

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
        SystemMessage(content=context),
        *_history_to_messages(history),
    ]

    result = await llm.ainvoke(messages)
    if not isinstance(result.content, str):
        logger.warning("Unexpected content type: %s", type(result.content))
    return result.content if isinstance(result.content, str) else str(result.content)
