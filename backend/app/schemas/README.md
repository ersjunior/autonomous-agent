# Schemas

Schemas **Pydantic v2** para validação e serialização dos contratos da API (entrada e saída). São o "DTO" da camada HTTP — separados dos modelos ORM (`app/models/`).

## Grupos

| Schema | Cobre |
|---|---|
| `user.py` | Login, registro, usuário atual (JWT) |
| `agent.py` | CRUD de agentes |
| `identity.py` | Identidade institucional (workspace + override por agente) |
| `channel.py` | Configuração de canais e webhooks |
| `lead.py` / `lead_base.py` | Leads e bases de leads |
| `campaign.py` | Campanhas outbound |
| `activation.py` | Janelas, cadência e agendamento de acionamento |
| `capacity.py` | Dimensionamento de capacidade (Erlang C) |
| `tabulacao.py` | Tabulações (desfecho) |
| `handoff.py` | Escalonamento para humano |
| `knowledge.py` | Upload e documentos da base de conhecimento |
| `settings.py` | Configurações dinâmicas (providers, áudio, identidade) |
| `dashboard.py` / `metrics.py` / `monitoring_attendance.py` | Indicadores, métricas e atendimentos |
| `tunnel.py` | Status do túnel Cloudflare |

## Convenção

Cada rota recebe um schema `*Create`/`*Update` e devolve um schema `*Read`/`*Response`, mantendo o modelo ORM fora do contrato público.
