"""Intent identification worker."""

from typing import Literal

from pydantic import BaseModel, Field

from agents.provider_factory import ProviderFactory
from app.core.config import settings

IntentType = Literal[
    "greeting",
    "question",
    "complaint",
    "purchase",
    "cancel",
    "escalate",
    "other",
]

ComplaintSeverity = Literal["low", "high"]

SYSTEM_PROMPT = """Você é um classificador de intenções para atendimento ao cliente.
Analise a mensagem atual do cliente e o histórico da conversa.
Identifique a intenção principal entre: greeting, question, complaint, purchase, cancel, escalate, other.
Extraia entidades relevantes (produto, pedido, problema, datas, valores, etc.) em um dicionário.
Atribua confidence entre 0 e 1 conforme sua certeza na classificação.

Regras para escalate (prioridade alta):
- Marque intent=escalate quando o cliente pedir EXPLICITAMENTE humano, atendente, pessoa real,
  supervisor ou falar com alguém (ex.: "quero falar com um humano", "me passa um atendente").
- Marque escalate também quando estiver muito frustrado e o caso exigir intervenção humana imediata.

Regras para complaint e complaint_severity (somente quando intent=complaint):
- complaint_severity=high: ameaça legal, xingamentos graves, risco de dano, acusação grave de fraude,
  tom de indignação extrema, promessa de processar/reclamar formalmente, situação inaceitável.
- complaint_severity=low: insatisfação leve ou moderada que o bot pode tentar resolver
  (ex.: demora, confusão, pedido de esclarecimento sobre problema menor).
- Para qualquer intent que NÃO seja complaint, use complaint_severity=low."""


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)
    complaint_severity: ComplaintSeverity = Field(
        default="low",
        description="Gravidade da reclamação quando intent=complaint; low nos demais casos",
    )


async def identify_intent(message: str, history: list[dict]) -> IntentResult:
    llm = ProviderFactory.get_llm()

    history_text = "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in history
    )
    user_content = message
    if history_text:
        user_content = f"Histórico:\n{history_text}\n\nMensagem atual:\n{message}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = await llm.complete(
        messages,
        temperature=settings.intent_temperature,
        structured_output_schema=IntentResult,
    )
    if not isinstance(result, IntentResult):
        raise TypeError(f"Expected IntentResult, got {type(result)}")

    if result.intent != "complaint":
        result.complaint_severity = "low"
    return result
