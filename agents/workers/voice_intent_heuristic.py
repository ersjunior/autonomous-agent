"""Heurística leve de intent para telefonia — evita chamada LLM extra no canal voice."""

from __future__ import annotations

import re
import unicodedata

from agents.workers.intent_agent import ComplaintSeverity, IntentResult, IntentType

# Confiança alta o suficiente para não escalar por incerteza (limiar 0.25).
VOICE_DEFAULT_CONFIDENCE = 0.85

_ESCALATE_PATTERNS = (
    r"\batendente\b",
    r"\bhumano\b",
    r"\bpessoa\s+real\b",
    r"\bsupervisor\b",
    r"\boperador\b",
    r"\btransfer",
    r"\bfalar\s+com\s+(?:um\s+)?(?:atendente|humano|algu[eé]m|pessoa)",
    r"\bme\s+passa\b",
)

_PURCHASE_PATTERNS = (
    r"\bquero\s+comprar\b",
    r"\bvou\s+comprar\b",
    r"\baceito\b",
    r"\bfechar\s+(?:o\s+)?neg[oó]cio\b",
    r"\bquero\s+contratar\b",
    r"\bpode\s+mandar\b",
    r"\bvou\s+levar\b",
    r"\bfechado\b",
)

_CANCEL_PATTERNS = (
    r"\bn[aã]o\s+quero\b",
    r"\bcancel",
    r"\bdesist",
    r"\bsem\s+interesse\b",
    r"\bn[aã]o\s+tenho\s+interesse\b",
    r"\bpare\s+de\s+ligar\b",
    r"\bn[aã]o\s+me\s+lig",
)

_COMPLAINT_HIGH_PATTERNS = (
    r"\bprocess",
    r"\badvogad",
    r"\bprocon\b",
    r"\bindign",
    r"\babsurdo\b",
    r"\binaceit[aá]vel\b",
    r"\bvergonha\b",
    r"\bfraude\b",
)

_SCHEDULE_PATTERNS = (
    r"\bagend",
    r"\bmarcar\b",
    r"\bmarcar\s+hor",
    r"\bremarc",
    r"\breuni",
    r"\bvisita\b",
    r"\btem\s+hor[aá]rio\b",
    r"\bquero\s+marcar\b",
    r"\bposso\s+marcar\b",
    r"\bhor[aá]rio\s+dispon",
    # Follow-ups após agendamento concluído na mesma ligação
    r"\boutr[oa]\s+hor[aá]rio",
    r"\boutr[oa]s?\s+hor[aá]rios",
    r"\bnovo\s+hor[aá]rio",
    r"\boutra\s+agenda",
    r"\b(?:ver|mostrar|tem|tinha|teria|queria)\s+.{0,20}hor[aá]rio",
    # data/dia com verbo de busca (evita falso positivo em "até outro dia")
    r"\b(?:tem|tinha|teria|ver|mostrar|queria|quero|preciso)\s+(?:\w+\s+){0,3}outr[oa]\s+(?:data|dia)\b",
)

_FAREWELL_PATTERNS = (
    r"\btchau\b",
    r"\bate\s+(?:logo|mais|breve)\b",
    r"\b(?:era|e)\s+so\s+isso\b",
    r"\bso\s+isso\s+mesmo\b",
    r"\bnao\s+preciso\s+de\s+mais\s+nada\b",
    r"\bpode\s+(?:encerrar|desligar)\b",
    r"\bpodemos\s+encerrar\b",
    r"\bso\s+isso\s+obrigad",
    r"\bnao,?\s+(?:era\s+)?so\s+isso\b",
)

# Só com wrap_up_pending ativo (resposta a "mais alguma coisa?").
_WRAP_UP_DECLINE_PATTERNS = (
    r"^(?:nao|não)$",
    r"^so\s+isso\b",
    r"^nao\s+preciso\b",
    r"^nao,?\s+obrigad",
    r"^obrigad",
)

_GREETING_PATTERNS = (
    r"^(?:ol[aá]|oi|bom\s+dia|boa\s+tarde|boa\s+noite|al[oô]|e\s+a[ií])\b",
)

FAREWELL_CONFIDENCE = 0.92


def _normalize(text: str) -> str:
    lowered = (text or "").lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _matches_any(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pat, normalized) for pat in patterns)


def matches_farewell_heuristic(message: str) -> bool:
    normalized = _normalize(message)
    if not normalized:
        return False
    return _matches_any(normalized, _FAREWELL_PATTERNS)


def matches_wrap_up_decline(message: str) -> bool:
    """Recusa curta após 'mais alguma coisa?' — só usar com wrap_up_pending."""
    normalized = _normalize(message)
    if not normalized or len(normalized) > 40:
        return False
    return _matches_any(normalized, _WRAP_UP_DECLINE_PATTERNS)


def identify_intent_voice_heuristic(message: str) -> IntentResult:
    """
    Classifica intent por palavras-chave (sem LLM).

    Preserva escalonamento, tabulação purchase/cancel e reclamações graves —
    os sinais críticos que dependem de intent no fluxo de voz.
    """
    normalized = _normalize(message)
    if not normalized:
        return IntentResult(intent="other", confidence=VOICE_DEFAULT_CONFIDENCE)

    if _matches_any(normalized, _ESCALATE_PATTERNS):
        return IntentResult(intent="escalate", confidence=0.95)

    if _matches_any(normalized, _PURCHASE_PATTERNS):
        return IntentResult(intent="purchase", confidence=0.9)

    if _matches_any(normalized, _CANCEL_PATTERNS):
        return IntentResult(intent="cancel", confidence=0.9)

    if _matches_any(normalized, _COMPLAINT_HIGH_PATTERNS):
        return IntentResult(
            intent="complaint",
            confidence=0.9,
            complaint_severity="high",
        )

    if _matches_any(normalized, _SCHEDULE_PATTERNS):
        return IntentResult(intent="schedule", confidence=0.9)

    if _matches_any(normalized, _FAREWELL_PATTERNS):
        return IntentResult(intent="farewell", confidence=FAREWELL_CONFIDENCE)

    if len(normalized) <= 40 and _matches_any(normalized, _GREETING_PATTERNS):
        return IntentResult(intent="greeting", confidence=0.9)

    return IntentResult(intent="question", confidence=VOICE_DEFAULT_CONFIDENCE)
