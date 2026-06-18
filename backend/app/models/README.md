# Models

Modelos **SQLAlchemy 2.0** (mapeamento ORM). O schema do banco é gerido por **migrations Alembic** (`backend/alembic/`) — esta pasta define as entidades, mas a criação/alteração de tabelas vem das migrations.

## Entidades

| Modelo | Tabela / papel |
|---|---|
| `user.py` | Usuários e autenticação |
| `agent.py` | Agentes de IA (personalidade, modo ATIVO/RECEPTIVO, identidade) |
| `channel.py` | Canais (`ChannelType`: `WHATSAPP`, `TELEGRAM`, `VOICE`) |
| `agent_channel_settings.py` | Configuração de canal por agente |
| `lead.py` / `lead_base.py` | Leads e suas bases (agrupamento) |
| `lead_interaction.py` | Interações registradas por lead |
| `campaign.py` | Campanhas outbound (modo ATIVO) |
| `agent_activation.py` | Janelas/estado de acionamento do agente |
| `queue_entry.py` | Fila receptiva (controle de capacidade) |
| `interaction.py` | Interações com embedding (**memória de longo prazo / pgvector**) |
| `knowledge.py` | Documentos e chunks da base de conhecimento (RAG) |
| `tabulacao.py` | Tabulações (desfecho do atendimento) |
| `app_setting.py` | Configurações dinâmicas (hot-reload) |
| `appointment.py` | Compromissos da agenda interna (`appointments`) |
| `availability_rule.py` | Regras semanais de disponibilidade — tenant ou agente (`availability_rules`) |
| `base.py` | Base declarativa comum (mixin de timestamps/PK) |

> A coluna de embedding em `interaction` usa `Vector` (pgvector) com dimensão definida por `EMBEDDING_DIMENSIONS` (768 Ollama / 1536 OpenAI), aplicada via migration.

Visão geral do backend: [`docs/backend.md`](../../../../docs/backend.md).
