"""OpenAI GPT LLM provider."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import BaseModel

from agents.providers.base import LLMProvider
from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"


def _to_langchain_messages(
    messages: list[dict[str, Any]],
) -> list[SystemMessage | HumanMessage | AIMessage]:
    lc_messages: list[SystemMessage | HumanMessage | AIMessage] = []
    for item in messages:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role in ("assistant", "ai"):
            lc_messages.append(AIMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))
    return lc_messages


class OpenAILLMProvider(LLMProvider):
    """GPT models via LangChain + OpenAI embeddings API."""

    @property
    def provider_name(self) -> str:
        return "openai"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        structured_output_schema: type[BaseModel] | None = None,
        max_tokens: int | None = None,
    ) -> str | BaseModel:
        llm_kwargs: dict[str, Any] = {
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
            "temperature": temperature,
        }
        if max_tokens is not None and max_tokens > 0:
            llm_kwargs["max_tokens"] = max_tokens
        llm = ChatOpenAI(**llm_kwargs)
        lc_messages = _to_langchain_messages(messages)
        if structured_output_schema is not None:
            structured_llm = llm.with_structured_output(structured_output_schema)
            return await structured_llm.ainvoke(lc_messages)
        result = await llm.ainvoke(lc_messages)
        content = result.content
        return content if isinstance(content, str) else str(content)

    async def embed(self, text: str) -> list[float]:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=settings.embedding_dimensions,
        )
        return response.data[0].embedding

    async def aclose(self) -> None:
        return None
