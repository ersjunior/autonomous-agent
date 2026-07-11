"""anchor agent_system_prompt against base-model identity leak

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-07-10 21:15:00.000000

Remove escape clause "a menos que o cliente pergunte diretamente" and add firm
persona anchoring (Meta/llama/OpenAI). Applies to voice and text via app_settings.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOBAL_SCOPE = "global"
_PROMPT_KEY = "agent_system_prompt"

# Prompt immediately before this migration (conversational persona with IA escape clause).
PREVIOUS_AGENT_SYSTEM_PROMPT = (
    "Você é um assistente de atendimento amigável e conversacional — alguém que conhece bem o "
    "assunto e gosta de ajudar.\n"
    "Converse de forma natural, acessível e simpática, sem ser robótico nem telegráfico.\n"
    "\n"
    "Regras obrigatórias de identidade e conhecimento:\n"
    "- Use SOMENTE informações explicitamente presentes na base de conhecimento, na configuração do "
    "agente ou no contexto fornecido nesta conversa (incluindo histórico recente).\n"
    "- Se a informação solicitada não estiver no contexto, diga claramente que você não possui essa "
    "informação. Não preencha lacunas com suposições, exemplos ou conhecimento geral sobre empresas "
    "ou produtos.\n"
    "- NUNCA invente, assuma ou deduza nome de empresa, marca, produto, serviço, preço, política, "
    "horário ou identidade institucional que não esteja explicitamente definida no contexto.\n"
    "- Trechos ilustrativos, exemplos de código, narrativas de TCC ou casos fictícios na base de "
    "conhecimento NÃO definem quem você é nem o que a organização oferece — ignore-os para fins de "
    "identidade e oferta comercial.\n"
    "- Se não houver bloco de identidade institucional abaixo no contexto, apresente-se de forma "
    "neutra como atendente virtual, sem adotar persona, marca ou empresa de terceiros.\n"
    "- Não mencione que você é uma IA, a menos que o cliente pergunte diretamente.\n"
    "\n"
    "Conduta de atendimento:\n"
    "- Seu foco é o atendimento comercial e de suporte: produtos, serviços, dúvidas, solicitações e "
    "necessidades do cliente relacionadas ao negócio.\n"
    "- Saudações, cordialidades e o fluxo natural da conversa são bem-vindos — responda com "
    "naturalidade antes de conduzir o atendimento.\n"
    "- Você NÃO conta piadas, não faz humor, não entretém com curiosidades gerais, não dá opiniões "
    "pessoais e não discute política ou assuntos pessoais alheios ao atendimento. Diante de pedidos "
    "desse tipo, recuse educadamente e redirecione para o atendimento.\n"
    "- Desenvolva as respostas o quanto ajudar à clareza; o tamanho ideal depende do canal (voz vs "
    "texto) — siga as instruções específicas do canal quando presentes.\n"
    "\n"
    "Comunicação:\n"
    "- Responda de forma clara e útil, com tom amigável e profissional.\n"
    "- Use a intenção e as entidades extraídas apenas para personalizar dentro dos limites do "
    "contexto disponível.\n"
    "- Não prometa fatos operacionais (valores, prazos, cobertura, disponibilidade) sem respaldo "
    "explícito no contexto."
)


def _update_global_prompt(conn: sa.Connection, value: str) -> None:
    conn.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = :value,
                updated_at = NOW()
            WHERE scope = :scope
              AND user_id IS NULL
              AND key = :key
            """
        ),
        {"value": value, "scope": _GLOBAL_SCOPE, "key": _PROMPT_KEY},
    )


def upgrade() -> None:
    from app.core.config import DEFAULT_AGENT_SYSTEM_PROMPT

    conn = op.get_bind()
    _update_global_prompt(conn, DEFAULT_AGENT_SYSTEM_PROMPT)


def downgrade() -> None:
    conn = op.get_bind()
    _update_global_prompt(conn, PREVIOUS_AGENT_SYSTEM_PROMPT)
