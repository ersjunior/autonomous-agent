"""Classificador de tabulação por IA — chamado só quando regras não resolvem."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from agents.provider_factory import ProviderFactory
from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você classifica o RESULTADO de um atendimento ao cliente.
Com base no texto da conversa / última mensagem, escolha UMA tabulação da lista fornecida.
Use somente códigos da lista. Se nenhuma se encaixar com confiança, retorne codigo vazio (null).
Priorize tabulações de negócio (NEG:*) para resultados comerciais e SIP:* apenas para falhas de telefonia explícitas."""


class TabulacaoClassificationResult(BaseModel):
    codigo: str | None = Field(
        default=None,
        description="Código exato da tabulação escolhida, ou null se incerto",
    )


async def classify_tabulacao(
    conversation_text: str,
    available: list[dict[str, str]],
) -> str | None:
    """
    Escolhe um código dentre ``available`` (itens com chaves codigo, nome, categoria).

    Retorna None se a IA não escolher um código válido da lista.
    """
    if not conversation_text or not conversation_text.strip():
        return None
    if not available:
        return None

    valid_codes = {item["codigo"] for item in available}
    catalog_lines = "\n".join(
        f"- {item['codigo']}: {item['nome']} ({item['categoria']})"
        for item in available
    )
    user_content = (
        f"Tabulações disponíveis:\n{catalog_lines}\n\n"
        f"Texto do atendimento:\n{conversation_text.strip()}\n\n"
        "Escolha o código mais adequado ou null."
    )

    llm = ProviderFactory.get_llm()
    try:
        result = await llm.complete(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=settings.intent_temperature,
            structured_output_schema=TabulacaoClassificationResult,
        )
    except Exception:
        logger.exception("classify_tabulacao: falha na chamada LLM")
        return None

    if not isinstance(result, TabulacaoClassificationResult):
        return None

    codigo = (result.codigo or "").strip()
    if not codigo or codigo not in valid_codes:
        logger.info(
            "classify_tabulacao: código inválido ou ausente (%r); sem tabulação",
            result.codigo,
        )
        return None
    return codigo
