"""Ollama local LLM provider."""

import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from agents.providers.base import LLMProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_EMBED_MODEL = "nomic-embed-text"

_RAW_LOG_MAX_CHARS = 500


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
        max_tokens: int | None = None,
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

        options: dict[str, float | int] = {"temperature": temperature}
        if max_tokens is not None and max_tokens > 0:
            options["num_predict"] = max_tokens

        request_body: dict[str, Any] = {
            "model": settings.ollama_model,
            "messages": payload_messages,
            "stream": False,
            "options": options,
        }
        if structured_output_schema is not None:
            request_body["format"] = "json"

        response = await self._client.post("/api/chat", json=request_body)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")

        if structured_output_schema is None:
            return content

        return self._coerce_structured_output(content, structured_output_schema)

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

    def _coerce_structured_output(
        self,
        content: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        """Parse LLM JSON output; never raises on malformed content."""
        parsed = self._parse_json_content(content)
        if parsed is not None:
            try:
                return schema.model_validate(parsed)
            except ValidationError as exc:
                logger.warning(
                    "Ollama structured output validation failed (%s); raw=%r",
                    exc,
                    _truncate_raw(content),
                )

        cleaned = self._strip_markdown_fences(content)
        if cleaned != content.strip():
            parsed = self._parse_json_content(cleaned)
            if parsed is not None:
                try:
                    return schema.model_validate(parsed)
                except ValidationError:
                    pass

        extracted = self._extract_json_object(content)
        if extracted:
            try:
                return schema.model_validate_json(extracted)
            except (ValidationError, ValueError):
                pass

        logger.warning(
            "Ollama JSON parse failed; using structured fallback. raw=%r",
            _truncate_raw(content),
        )
        return self._structured_fallback(schema)

    @staticmethod
    def _structured_fallback(schema: type[BaseModel]) -> BaseModel:
        """Safe defaults when the LLM returns unparseable structured output."""
        name = schema.__name__
        if name == "IntentResult":
            return schema.model_validate(
                {
                    "intent": "question",
                    "confidence": 0.5,
                    "entities": {},
                    "complaint_severity": "low",
                }
            )
        if name == "TabulacaoClassificationResult":
            return schema.model_validate({"codigo": None})

        try:
            return schema.model_construct()
        except Exception:
            return schema.model_validate({})

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        match = re.match(r"^```(?:json)?\s*\n?(.*)\n?```\s*$", stripped, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        lines = stripped.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """Return the first balanced {...} substring, ignoring braces inside strings."""
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    @classmethod
    def _parse_json_content(cls, content: str) -> Any | None:
        """
        Best-effort JSON extraction from Ollama chat content.

        Tolerates markdown fences and leading/trailing prose. Returns None instead
        of raising when no valid JSON can be recovered.
        """
        if not content or not str(content).strip():
            return None

        candidates: list[str] = []
        stripped = content.strip()
        candidates.append(stripped)
        candidates.append(cls._strip_markdown_fences(stripped))

        extracted = cls._extract_json_object(stripped)
        if extracted:
            candidates.append(extracted)

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        return None


def _truncate_raw(content: str) -> str:
    text = content or ""
    if len(text) <= _RAW_LOG_MAX_CHARS:
        return text
    return text[:_RAW_LOG_MAX_CHARS] + "…"
