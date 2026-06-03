# Backend

API principal do autonomous-agent (FastAPI / Python 3.12).

## Responsabilidades

- REST API em `/api/v1/` (auth, agents, channels, leads, campaigns)
- WebSocket de monitoramento (`/api/v1/monitoring/ws`)
- Webhooks de canais (ex.: WhatsApp/Twilio)
- Seed do usuário admin em desenvolvimento

A lógica de IA (LangGraph, provedores, canais) fica em `agents/` na raiz — importada via `PYTHONPATH`.

## Startup (lifespan)

No arranque do container, `app/main.py`:

1. Cria a extensão PostgreSQL `vector` (pgvector)
2. Executa `alembic upgrade head` (schema via migrations — fonte única)
3. Faz seed do admin (`admin@admin.com` / `admin`) se não existir

`make migrate` continua disponível e é idempotente quando o banco já está no `head`.

## Desenvolvimento local

```bash
# Com Docker (recomendado)
make up
make shell-backend

# Migrations manuais
make migrate
```

Variáveis: ver `.env.example` na raiz. Dentro dos containers, `DATABASE_URL` usa hostnames Docker (`postgres`, `redis`).

## Estrutura

```
backend/
├── app/
│   ├── api/v1/      # rotas REST + WebSocket
│   ├── core/        # config, database, security, seed
│   ├── models/      # SQLAlchemy
│   └── schemas/     # Pydantic
├── alembic/         # migrations
└── Dockerfile
```
