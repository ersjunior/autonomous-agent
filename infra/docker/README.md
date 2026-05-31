# Docker

Configurações Docker Compose para ambientes local (dev) e produção.

## Arquivos

| Arquivo | Uso |
|---------|-----|
| `docker-compose.yml` | Base — postgres, redis, backend, frontend, worker |
| `docker-compose.dev.yml` | Override DEV — worker com loglevel debug |
| `docker-compose.prod.yml` | Override PRD — sem volumes, frontend standalone, workers |
| `postgres/init.sql` | Habilita extensão `vector` (pgvector) na inicialização |

## Comandos (a partir da raiz do projeto)

```bash
make up          # DEV
make prod-up     # PRD
make down        # parar DEV
make prod-down   # parar PRD
```

Antes de subir, copie `.env.example` para `.env` e ajuste `DEBUG` e `SECRET_KEY`.

## Portas padrão (DEV)

| Serviço | Porta no host |
|---------|---------------|
| Backend | 8000 |
| Frontend | 3000 |
| PostgreSQL | 25432 |
| Redis | 16379 |

## Serviços

- **backend** e **worker** compartilham `backend/Dockerfile` (inclui `agents/` e `worker/`)
- **frontend** usa multi-stage: `dev` (hot-reload) ou `runner` (produção standalone)
- Variáveis de app são lidas de `../../.env` via `--env-file` no Makefile
