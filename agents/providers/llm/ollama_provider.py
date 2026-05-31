"""Ollama local LLM provider."""

import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from agents.providers.base import LLMProvider
from app.core.config import settings

OLLAMA_EMBED_MODEL = "nomic-embed-text"


class OllamaLLMProvider(LLMProvider):
    """LLaMA / Mistral / Qwen via Ollama HTTP API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=httpx.Timeout(300.0),
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        structured_output_schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        payload_messages = [dict(m) for m in messages]
        if structured_output_schema is not None:
            schema = structured_output_schema.model_json_schema()
            format_instruction = (
                "Responda APENAS com um objeto JSON válido que obedeça "
                f"este schema (sem markdown, sem texto extra):\n{json.dumps(schema, ensure_ascii=False)}"
            )
            payload_messages = [
                {"role": "system", "content": format_instruction},
                *payload_messages,
            ]

        response = await self._client.post(
            "/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": payload_messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")

        if structured_output_schema is None:
            return content

        parsed = self._parse_json_content(content)
        try:
            return structured_output_schema.model_validate(parsed)
        except ValidationError:
            return structured_output_schema.model_validate_json(content)

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post(
            "/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        )
        response.raise_for_status()
        data = response.json()
        embedding = data.get("embedding")
        if not embedding:
            raise ValueError("Ollama embeddings response missing 'embedding' field")
        return embedding

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _parse_json_content(content: str) -> Any:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return json.loads(text)
