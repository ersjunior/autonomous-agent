# Autonomous Agent

[![Licença: MIT](https://img.shields.io/badge/Licença-MIT-blue.svg)](LICENSE)

Sistema multi-agente de inteligência artificial para atendimento autônomo de clientes em múltiplos canais (WhatsApp, Telegram, voz e vídeo). O agente opera em modo **ativo** (campanhas outbound para leads) ou **receptivo** (resposta a mensagens recebidas), orquestrado com LangGraph e GPT-4o.

## Arquitetura

O projeto é composto pelos seguintes serviços:

| Serviço    | Função |
|------------|--------|
| **Backend** | API REST FastAPI — autenticação, CRUD, webhooks e WebSocket de monitoramento |
| **Frontend** | Dashboard Next.js 15 para gestão de agentes, canais, leads e campanhas |
| **Worker** | Celery — processamento assíncrono de mensagens inbound e campanhas outbound |
| **PostgreSQL** | Banco relacional com extensão pgvector para memória de longo prazo |
| **Redis** | Cache de conversas (TTL), broker Celery, pub/sub de eventos em tempo real |

Fluxo resumido: mensagens entram via webhook ou campanha → Worker ou Backend delega ao grafo LangGraph em `agents/` → intent + resposta → envio pelo canal → eventos publicados no Redis → dashboard consome via WebSocket.

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose v2
- [Python 3.12](https://www.python.org/downloads/) (desenvolvimento local opcional)
- [Node.js 20+](https://nodejs.org/) (desenvolvimento local do frontend opcional)

## Instalação

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/autonomous-agent.git
cd autonomous-agent
```

### 2. Copiar variáveis de ambiente

```bash
cp .env.example .env
```

### 3. Configurar ambiente (DEV ou PRD)

Edite o `.env` na raiz do projeto. As chaves mais importantes para alternar entre desenvolvimento e produção:

| Variável | Desenvolvimento | Produção |
|----------|-----------------|----------|
| `DEBUG` | `true` | `false` |
| `SECRET_KEY` | qualquer valor para testes | chave forte e aleatória (mín. 32 caracteres) |

Preencha também as credenciais dos serviços que você vai utilizar (OpenAI, Twilio, etc.).

**Importante:** dentro dos containers Docker, `DATABASE_URL` e `REDIS_URL` usam os hostnames `postgres` e `redis` (definidos automaticamente no Compose). Os valores `localhost` no `.env` servem para acesso **fora** do Docker (migrations locais, DBeaver, etc.).

### 4. Subir os containers

**Desenvolvimento** (hot-reload, volumes montados):

```bash
make up
```

**Produção** (imagens baked, sem reload, DB/Redis sem portas expostas):

```bash
make prod-up
```

Equivalente manual:

```bash
# DEV
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d --build

# PRD
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.prod.yml up -d --build
```

### 5. Aplicar migrations

```bash
make migrate
```

### 6. Acessar a aplicação

| Recurso | URL |
|---------|-----|
| Dashboard | [http://localhost:3000](http://localhost:3000) |
| API (Swagger) | [http://localhost:8000/docs](http://localhost:8000/docs) |
| PostgreSQL (host) | `localhost:25432` |
| Redis (host) | `localhost:16379` |

Na primeira subida, o backend cria automaticamente um usuário admin padrão:

| Campo | Valor |
|-------|-------|
| Email | `admin@admin.com` |
| Senha | `admin` |

> Altere ou remova esse seed antes de ir para produção.

## Variáveis de ambiente

### Aplicação

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `DEBUG` | Modo debug (`true` em DEV, `false` em PRD) | Sim |
| `SECRET_KEY` | Chave secreta para JWT | Sim |
| `FRONTEND_URL` | URL do frontend (CORS) | Sim |

### Banco e filas

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `POSTGRES_USER` | Usuário PostgreSQL | Sim |
| `POSTGRES_PASSWORD` | Senha PostgreSQL | Sim |
| `POSTGRES_DB` | Nome do banco | Sim |
| `POSTGRES_PORT` | Porta exposta no host (padrão DEV: `25432`) | Sim |
| `DATABASE_URL` | Connection string (host local) | Sim |
| `REDIS_PORT` | Porta exposta no host (padrão DEV: `16379`) | Sim |
| `REDIS_URL` | URL Redis (cache + pub/sub) | Sim |
| `CELERY_BROKER_URL` | Broker Celery (Redis) | Sim |
| `CELERY_RESULT_BACKEND` | Backend de resultados Celery | Sim |

### Integrações

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `OPENAI_API_KEY` | API OpenAI (GPT-4o + Whisper) | Sim |
| `OPENAI_MODEL` | Modelo LLM (padrão: `gpt-4o`) | Sim |
| `TWILIO_ACCOUNT_SID` | Twilio — WhatsApp e voz | Canal WhatsApp/Voz |
| `TWILIO_AUTH_TOKEN` | Token Twilio | Canal WhatsApp/Voz |
| `TWILIO_PHONE_NUMBER` | Número Twilio | Canal WhatsApp/Voz |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram | Canal Telegram |
| `ELEVENLABS_API_KEY` | TTS ElevenLabs | Canal Voz |
| `ELEVENLABS_VOICE_ID` | ID da voz ElevenLabs | Canal Voz |
| `DID_API_KEY` | D-ID avatar em vídeo | Canal Vídeo |

### Frontend

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `NEXT_PUBLIC_API_URL` | URL da API para o frontend | Sim |
| `FRONTEND_PORT` | Porta do frontend (padrão: `3000`) | Não |
| `BACKEND_PORT` | Porta do backend (padrão: `8000`) | Não |

## Endpoints principais da API

Base URL: `http://localhost:8000/api/v1`

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/health` | Health check (raiz, sem prefixo `/api/v1`) |
| `POST` | `/auth/register` | Cadastro de usuário |
| `POST` | `/auth/login` | Login — retorna JWT |
| `GET/POST` | `/agents/` | Listar / criar agentes |
| `GET/PUT/DELETE` | `/agents/{id}` | Detalhe / atualizar / remover agente |
| `GET/POST` | `/channels/` | Listar / criar canais |
| `GET/PUT/DELETE` | `/channels/{id}` | Detalhe / atualizar / remover canal |
| `POST` | `/channels/webhooks/whatsapp` | Webhook Twilio (WhatsApp) |
| `GET/POST` | `/leads/` | Listar / criar leads |
| `GET/PUT/DELETE` | `/leads/{id}` | Detalhe / atualizar / remover lead |
| `GET/POST` | `/campaigns/` | Listar / criar campanhas |
| `GET/PUT/DELETE` | `/campaigns/{id}` | Detalhe / atualizar / remover campanha |
| `POST` | `/campaigns/{id}/start` | Iniciar campanha ativa (dispara mensagens aos leads) |
| `WS` | `/monitoring/ws` | Feed em tempo real de eventos do agente |

Rotas autenticadas exigem header `Authorization: Bearer <token>`.

## Estrutura de pastas

```
autonomous-agent/
├── agents/              # IA — LangGraph, workers LLM, canais, memória, tools
│   ├── channels/        # WhatsApp, Telegram, voz, vídeo
│   ├── orchestrator/    # Grafo LangGraph + router + state
│   ├── workers/         # Intent e response agents
│   ├── memory/          # Redis (curto prazo) + pgvector (longo prazo)
│   ├── tools/           # CRM, calendário, base de conhecimento
│   └── events.py        # Pub/sub Redis para monitoramento
├── backend/             # API FastAPI
│   └── app/
│       ├── api/v1/      # Rotas REST e WebSocket
│       ├── core/        # Config, database, security, seed
│       ├── models/      # SQLAlchemy
│       └── schemas/     # Pydantic
├── frontend/            # Dashboard Next.js 15
│   └── src/
│       ├── app/         # App Router (login, dashboard)
│       └── components/  # UI, layout, providers (tema claro/escuro)
├── worker/              # Celery — campanhas e mensagens inbound
├── infra/docker/        # docker-compose.yml + overrides dev/prod
├── tests/               # Testes automatizados
└── docs/                # Documentação adicional
```

## Comandos úteis (Makefile)

### Desenvolvimento

```bash
make up              # Sobe stack DEV (build + hot-reload)
make down            # Para containers DEV
make logs            # Logs em tempo real
make migrate         # Alembic upgrade head
make shell-backend   # Shell bash no container backend
make test            # pytest
make lint            # ruff check
```

### Produção

```bash
make prod-up         # Sobe stack PRD (sem volumes de código)
make prod-down       # Para containers PRD
make prod-logs       # Logs da stack PRD
```

## Docker — perfis dev e prod

| Aspecto | DEV (`make up`) | PRD (`make prod-up`) |
|---------|-----------------|------------------------|
| Backend | uvicorn com `--reload` | uvicorn com 4 workers |
| Frontend | `npm run dev` (target `dev`) | build standalone (target `runner`) |
| Volumes | código montado no container | imagem baked, sem bind mounts |
| Postgres/Redis | portas `25432` / `16379` no host | portas internas apenas |
| Worker | loglevel `debug` | loglevel `info`, concurrency 4 |

Arquivos Compose:

```
infra/docker/
├── docker-compose.yml       # base (serviços + defaults DEV)
├── docker-compose.dev.yml   # override DEV (worker debug)
├── docker-compose.prod.yml    # override PRD
└── postgres/init.sql          # extensão pgvector no init
```

## Desenvolvido como TCC

Este projeto foi desenvolvido como Trabalho de Conclusão de Curso (TCC) intitulado **"Do operador ao Agente: Transformando um atendente de telemarketing em um Agente de Inteligência Artificial Autônomo"**, apresentado ao **ICMC** (Instituto de Ciências Matemáticas e de Computação) da **USP** (Universidade de São Paulo).

O objetivo acadêmico é demonstrar a viabilidade de substituir fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional e escalar para atendimento humano quando necessário — integrando múltiplos canais de comunicação em uma arquitetura moderna baseada em microsserviços e LLMs.
