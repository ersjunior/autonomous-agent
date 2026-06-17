# Backend

API REST em FastAPI (Python 3.12) que concentra autenticação, CRUD, webhooks dos canais, WebSocket de monitoramento e as regras de negócio do sistema.

## Estrutura
backend/app/

├── main.py            # App FastAPI, CORS, lifespan (migrations + seed + bootstrap de settings)

├── api/v1/            # Routers REST + WebSocket

├── core/

│   ├── config.py        # Settings (pydantic-settings)

│   ├── database.py      # Sessão async do SQLAlchemy

│   ├── security.py      # JWT + bcrypt

│   ├── authorization.py # Regras is_system / ownership

│   ├── seed.py          # Admin, 3 canais, 2 agentes, 16 tabulações

│   ├── activation_*.py  # Defaults, janela e cadência de acionamento

│   ├── erlang.py        # Erlang C (planejamento de capacidade)

│   └── telegram_setup.py# setWebhook do Telegram (modo webhook)

├── models/            # Modelos SQLAlchemy

├── schemas/           # Schemas Pydantic v2

└── services/          # Regras de negócio (acionamento, capacidade, handoff, KB, settings, voz, ...)

## Routers (API v1)

Todas as rotas têm prefixo `/api/v1` (exceto `/health`). As rotas autenticadas exigem `Authorization: Bearer <token>`.

| Router | Função |
|---|---|
| `auth` | Cadastro e login (retorna JWT) |
| `agents` | CRUD de agentes (ACTIVE/RECEPTIVE) + identidade por agente (`PATCH /{id}/identity`) |
| `channels` | CRUD de canais + webhooks (WhatsApp/Telegram/Voz) + status de entrega WhatsApp + serve áudio outbound |
| `lead_bases` | Bases de leads, importação CSV, devolutiva em Excel, métricas por base |
| `leads` | CRUD de leads |
| `campaigns` | CRUD de campanhas + start/stop + métricas |
| `activation` | Configuração por canal, liga/desliga, teste ad-hoc (test-dispatch), histórico |
| `metrics` | Métricas de fila |
| `capacity` | Estimativa de capacidade (hardware + Erlang C) |
| `monitoring` | WebSocket de eventos em tempo real + histórico de atendimentos |
| `handoff` | Modo humano: listar, assumir, finalizar, reativar |
| `knowledge` | CRUD de documentos da base de conhecimento (KB) + upload (`.txt`/`.pdf`/`.docx`) e cadastro manual |
| `settings` | Leitura/escrita de settings com hot-reload + identidade do workspace (`/settings/identity`) + amostra/teste de voz |
| `tabulacoes` | Catálogo de tabulações (call center) |
| `tunnel` | Status do túnel Cloudflare |

## Autenticação e multi-tenant

- **Autenticação:** JWT Bearer, emitido no login e validado em cada requisição (`core/security.py`).
- **Autorização** (`core/authorization.py`):
  - Registros marcados como `is_system=true` são visíveis a todos, mas **somente leitura** (tentativas de alterar retornam 403).
  - Os demais registros são filtrados por `user_id` — um usuário não enxerga dados de outro (404 para recursos de terceiros).
  - Bases de leads derivam o dono a partir da campanha associada.

## Settings dinâmicas (hot-reload)

O sistema permite alterar parâmetros de operação (seleção de provider de LLM/STT/TTS, prompts, parâmetros de RAG, voz, handoff) **sem reiniciar** os serviços. A identidade institucional (workspace e por agente) também é editável em runtime, separada da KB.

- As configurações ficam na tabela `app_settings`, restritas a uma whitelist (`MANAGED_SETTINGS`) organizada em categorias: `llm`, `stt`, `tts`, `agent`, `system`.
- Ao salvar via `PUT /api/v1/settings`, o sistema incrementa uma versão no Redis e publica um evento de invalidação.
- Backend e workers recarregam as settings do banco quando detectam mudança de versão (ou após um TTL curto), garantindo que a alteração se propague para o processamento das mensagens.
- A inicialização (`lifespan` do backend e `worker_process_init` do Celery) faz o bootstrap das settings.

A interface correspondente está em `/dashboard/settings` (veja [frontend.md](frontend.md)).

## Inicialização

No startup, o backend executa em sequência: aplicação das migrations (Alembic), seed idempotente (admin, canais, agentes, tabulações) e bootstrap das settings. Isso garante que um ambiente novo suba pronto para uso.

Para os modelos e relações de dados, veja [agentes.md](agentes.md) (memória/RAG) e [configuracao.md](configuracao.md) (variáveis).
