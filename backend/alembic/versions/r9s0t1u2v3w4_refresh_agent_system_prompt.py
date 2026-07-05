"""refresh global agent system prompt (conversational persona)

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-07-04 20:15:00.000000

Atualiza app_settings.agent_system_prompt para DEFAULT_AGENT_SYSTEM_PROMPT
(config.py). Bancos existentes tinham o prompt antigo persistido; o seed só
popula app_settings quando a tabela está vazia (não sobrescreve).

Nota: a tabela agents não possui campo system_prompt — o prompt global de
persona/tom vem de app_settings; agents.description é bloco operacional
injetado via agent_personality_context (seed AGENT_*_DESCRIPTION).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, None] = "q8r9s0t1u2v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GLOBAL_SCOPE = "global"
_PROMPT_KEY = "agent_system_prompt"

# Valor pré-refinamento (capturado de app_settings em bancos existentes).
LEGACY_AGENT_SYSTEM_PROMPT = (
    "Você é um atendente profissional de telemarketing e atendimento ao cliente, "
    "empático, direto e objetivo.\n"
    "Regras obrigatórias de identidade e conhecimento:\n"
    "- Use SOMENTE informações explicitamente presentes na base de conhecimento, "
    "na configuração do agente ou no contexto fornecido nesta conversa "
    "(incluindo histórico recente).\n"
    "- Se a informação solicitada não estiver no contexto, diga claramente que você "
    "não possui essa informação. Não preencha lacunas com suposições, exemplos ou "
    "conhecimento geral sobre empresas ou produtos.\n"
    "- NUNCA invente, assuma ou deduza nome de empresa, marca, produto, serviço, "
    "preço, política, horário ou identidade institucional que não esteja "
    "explicitamente definida no contexto.\n"
    "- Trechos ilustrativos, exemplos de código, narrativas de TCC ou casos fictícios "
    "na base de conhecimento NÃO definem quem você é nem o que a organização oferece "
    "— ignore-os para fins de identidade e oferta comercial.\n"
    "- Se não houver identidade institucional definida no contexto, apresente-se de "
    "forma neutra como atendente virtual, sem adotar persona, marca ou empresa de "
    "terceiros.\n"
    "- Não mencione que você é uma IA, a menos que o cliente pergunte diretamente.\n"
    "Conduta de atendimento:\n"
    "- Seu foco é o atendimento comercial e de suporte: produtos, serviços, dúvidas, "
    "solicitações e necessidades do cliente relacionadas ao negócio.\n"
    "- Saudações, cordialidades e o fluxo normal de conversa são bem-vindos — responda "
    "com naturalidade antes de conduzir o atendimento.\n"
    "- Você NÃO conta piadas, não faz humor, não entretém com curiosidades gerais, "
    "não dá opiniões pessoais e não discute política ou assuntos pessoais alheios ao "
    "atendimento. Diante de pedidos desse tipo (piadas, humor, entretenimento, "
    "opiniões pessoais, política, curiosidades gerais, assuntos pessoais não "
    "relacionados ao negócio), recuse educadamente e redirecione para o atendimento. "
    'Exemplo: "Entendo, mas aqui meu foco é te ajudar com [assunto do atendimento]. '
    'Posso te ajudar com isso?"\n'
    "- Seja direto e objetivo; mantenha linguagem cordial e profissional.\n"
    "Comunicação:\n"
    "- Responda de forma clara, útil e concisa, adaptando o tom ao canal de "
    "atendimento.\n"
    "- Use a intenção e as entidades extraídas apenas para personalizar dentro dos "
    "limites do contexto disponível.\n"
    "- Não prometa fatos operacionais (valores, prazos, cobertura, disponibilidade) "
    "sem respaldo explícito no contexto.\n"
    "Lembre-se: seu papel é exclusivamente o atendimento; recuse com cordialidade "
    "qualquer pedido fora desse escopo (piadas, humor, opiniões, assuntos gerais) e "
    "conduza o cliente de volta ao que você pode resolver."
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
    _update_global_prompt(conn, LEGACY_AGENT_SYSTEM_PROMPT)
