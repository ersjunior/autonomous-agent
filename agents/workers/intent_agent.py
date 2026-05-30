"""Intent identification worker."""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

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

SYSTEM_PROMPT = """Você é um classificador de intenções para atendimento ao cliente.
Analise a mensagem atual do cliente e o histórico da conversa.
Identifique a intenção principal entre: greeting, question, complaint, purchase, cancel, escalate, other.
Extraia entidades relevantes (produto, pedido, problema, datas, valores, etc.) em um dicionário.
Atribua confidence entre 0 e 1 conforme sua certeza na classificação.
Use escalate quando o cliente pedir humano, estiver muito frustrado ou o caso exigir intervenção humana."""


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)


async def identify_intent(message: str, history: list[dict]) -> IntentResult:
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    structured_llm = llm.with_structured_output(IntentResult)

    history_text = "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in history
    )
    user_content = message
    if history_text:
        user_content = f"Histórico:\n{history_text}\n\nMensagem atual:\n{message}"

    result = await structured_llm.ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
    )
    return result
