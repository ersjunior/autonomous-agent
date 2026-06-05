"""
Mapeamento regras → código de tabulação.

Política de atribuição (T-2):
  1) SIP (futuro webhook Twilio/Asterisk) — sip_code → SIP:*
  2) Regras intent/status — resolve_tabulacao_by_rules
  3) IA — só quando regras não resolvem e o atendimento atingiu momento de classificação

Decisões documentadas:
  - purchase → NEG:VENDA (venda concretizada, não NEG:SUCESSO genérico)
  - cancel → NEG:RECUSADO (recusa explícita; catálogo ampliado na T-2)
  - escalonamento (B-1) → NEG:ESCALADO via flag ``escalated`` ou intent escalate
  - nao_atendido → NEG:AUSENTE (cadência/sweep sem resposta do cliente)
  - erro → sem tabulação (falha técnica de acionamento; eixo status já cobre)
  - em_andamento sem sinal claro → sem tabulação (evita ruído na planilha)
"""

from __future__ import annotations

from typing import Final

# Override em runtime (testes) se necessário; padrão imutável em produção.
INTENT_TO_CODIGO: dict[str, str] = {
    "purchase": "NEG:VENDA",
    "cancel": "NEG:RECUSADO",
    "escalate": "NEG:ESCALADO",
}

# Tabulação de sistema quando o bot encaminha para humano (B-1).
ESCALATION_TABULACAO_CODIGO: Final[str] = "NEG:ESCALADO"

STATUS_TO_CODIGO: dict[str, str] = {
    "nao_atendido": "NEG:AUSENTE",
    # "erro" deliberadamente omitido — sem tabulação de negócio clara
}

# Códigos SIP seed (SIP:NNN). Chave aceita "486" ou "SIP:486".
SIP_RESPONSE_CODES: Final[frozenset[str]] = frozenset(
    {
        "SIP:200",
        "SIP:486",
        "SIP:480",
        "SIP:487",
        "SIP:404",
        "SIP:603",
        "SIP:408",
        "SIP:484",
    }
)


def normalize_sip_code(sip_code: str) -> str | None:
    """Normaliza para formato SIP:NNN presente no catálogo."""
    raw = (sip_code or "").strip().upper()
    if not raw:
        return None
    if raw.startswith("SIP:"):
        return raw if raw in SIP_RESPONSE_CODES else None
    if raw.isdigit():
        candidate = f"SIP:{raw}"
        return candidate if candidate in SIP_RESPONSE_CODES else None
    return None


def resolve_tabulacao_for_escalation() -> str:
    """Código fixo quando ``should_escalate`` — encerramento do atendimento pelo bot."""
    return ESCALATION_TABULACAO_CODIGO


def resolve_tabulacao_by_rules(
    intent: str | None,
    status_interno: str | None,
    channel: str | None = None,
) -> str | None:
    """
    Retorna código de tabulação ou None se as regras não resolverem.

    ``channel`` reservado para regras futuras por canal (ex.: voz vs texto).
    """
    _ = channel  # gancho futuro

    intent_key = (intent or "").lower()
    if intent_key in INTENT_TO_CODIGO:
        return INTENT_TO_CODIGO[intent_key]

    status_key = (status_interno or "").lower()
    if status_key in STATUS_TO_CODIGO:
        return STATUS_TO_CODIGO[status_key]

    return None


def resolve_tabulacao_by_sip(sip_code: str) -> str | None:
    """Mapeia código de resposta SIP para tabulação TELEFONIA."""
    return normalize_sip_code(sip_code)
