"""Critérios de escalonamento para humano (B-1) — módulo puro, sem I/O."""

ESCALATION_CONFIDENCE_THRESHOLD = 0.25


def resolve_should_escalate(
    intent: str,
    confidence: float,
    complaint_severity: str = "low",
) -> bool:
    """
    Critérios de escalonamento (B-1):
      a) intent == escalate (pedido explícito de humano ou frustração extrema)
      b) confidence < ESCALATION_CONFIDENCE_THRESHOLD (incerteza na classificação)
      c) intent == complaint AND complaint_severity == high (reclamação grave)
    Reclamações leves (severity=low) não escalam — o bot tenta resolver em generate_response.
    """
    if intent == "escalate":
        return True
    if confidence < ESCALATION_CONFIDENCE_THRESHOLD:
        return True
    if intent == "complaint" and (complaint_severity or "low").lower() == "high":
        return True
    return False
