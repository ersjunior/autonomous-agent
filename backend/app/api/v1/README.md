# API v1

Rotas REST e WebSocket da API, versão 1. Todas montadas em `api_router` (`__init__.py`) sob o prefixo `/api/v1`.

## Routers

| Router | Responsabilidade |
|---|---|
| `auth.py` | Login JWT, registro e usuário atual |
| `agents.py` | CRUD de agentes + **identidade institucional** por agente |
| `channels.py` | Configuração de canais e **webhooks** (WhatsApp inbound/status, Telegram, Voz) |
| `lead_bases.py` | Bases de leads (agrupamento de contatos) |
| `leads.py` | CRUD/import de leads (CSV) |
| `campaigns.py` | Campanhas outbound (modo ATIVO) e seu ciclo de vida |
| `activation.py` | Acionamento: janelas de horário, cadência e agendamento |
| `capacity.py` | Capacidade receptiva (modelo Erlang C) e dimensionamento |
| `tabulacoes.py` | Tabulações (classificação de desfecho do atendimento) |
| `handoff.py` | Escalonamento para atendimento humano (modo humano) |
| `knowledge.py` | Base de conhecimento: upload, ingestão e listagem de documentos (RAG) |
| `settings.py` | Configurações dinâmicas (hot-reload) — providers, áudio, **identidade** do workspace |
| `dashboard.py` | Agregados e indicadores do painel |
| `metrics.py` | Métricas detalhadas (por agente, atendimento, etc.) |
| `monitoring.py` | WebSocket de monitoramento em tempo real (alimentado por Redis pub/sub) |
| `tunnel.py` | Status e controle do túnel Cloudflare (exposição pública para webhooks) |

## Padrões

- Rotas validam/serializam com schemas Pydantic (`app/schemas/`) e delegam a regra para `app/services/`.
- Autenticação por JWT (`app/core/security.py`); autorização/ownership em `app/core/authorization.py`.

Referência de endpoints e exemplos: [`docs/backend.md`](../../../../docs/backend.md).
