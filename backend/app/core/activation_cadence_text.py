"""Textos fixos da Camada C (cadência / follow-up)."""

FOLLOWUP_TRIGGER_MESSAGE = (
    "[Sistema] O lead não respondeu à mensagem anterior. "
    "Gere uma mensagem curta e cordial de follow-up para reengajar o contato. "
    "NÃO repita a abordagem inicial."
)

CLOSE_DEVOLUTIVA = "Encerrado: esgotadas tentativas sem resposta do lead."

# Marcador temporário entre enfileirar follow-up e o worker concluir o envio.
FOLLOWUP_ENQUEUED_MARKER = "__followup_enqueued__"
