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
- [Node.js 20](https://nodejs.org/) (desenvolvimento local do frontend opcional)

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

### 3. Preencher as chaves obrigatórias

Edite o arquivo `.env` com as credenciais dos serviços que você vai utilizar (veja a tabela abaixo). No Docker, `DATABASE_URL` e `REDIS_URL` usam os hostnames `postgres` e `redis`; para execução local fora do Compose, use `localhost`.

### 4. Subir os containers

```bash
make up
# ou: docker compose -f infra/docker/docker-compose.yml up -d
```

### 5. Aplicar migrations

```bash
make migrate
```

Acesse o dashboard em [http://localhost:3000](http://localhost:3000) e a API em [http://localhost:8000/docs](http://localhost:8000/docs).

## Variáveis de ambiente obrigatórias

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `SECRET_KEY` | Chave secreta para JWT | Sim |
| `DATABASE_URL` | Connection string PostgreSQL | Sim |
| `REDIS_URL` | URL Redis (cache + pub/sub) | Sim |
| `CELERY_BROKER_URL` | Broker Celery (Redis) | Sim |
| `CELERY_RESULT_BACKEND` | Backend de resultados Celery | Sim |
| `OPENAI_API_KEY` | API OpenAI (GPT-4o + Whisper) | Sim |
| `OPENAI_MODEL` | Modelo LLM (padrão: `gpt-4o`) | Sim |
| `TWILIO_ACCOUNT_SID` | Twilio — WhatsApp e voz | Canal WhatsApp/Voz |
| `TWILIO_AUTH_TOKEN` | Token Twilio | Canal WhatsApp/Voz |
| `TWILIO_PHONE_NUMBER` | Número Twilio | Canal WhatsApp/Voz |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram | Canal Telegram |
| `ELEVENLABS_API_KEY` | TTS ElevenLabs | Canal Voz |
| `ELEVENLABS_VOICE_ID` | ID da voz ElevenLabs | Canal Voz |
| `DID_API_KEY` | D-ID avatar em vídeo | Canal Vídeo |
| `NEXT_PUBLIC_API_URL` | URL da API para o frontend | Sim (frontend) |

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
│   ├── orchestrator/    # Grafo LangGraph
│   ├── workers/         # Intent e response agents
│   ├── memory/          # Redis (curto prazo) + pgvector (longo prazo)
│   ├── tools/           # CRM, calendário, base de conhecimento
│   └── events.py        # Pub/sub Redis para monitoramento
├── backend/             # API FastAPI
│   └── app/
│       ├── api/v1/      # Rotas REST e WebSocket
│       ├── core/        # Config, database, security
│       ├── models/      # SQLAlchemy
│       └── schemas/     # Pydantic
├── frontend/            # Dashboard Next.js 15
├── worker/              # Celery — campanhas e mensagens inbound
├── infra/docker/        # docker-compose.yml
├── tests/               # Testes automatizados
└── docs/                # Documentação adicional
```

## Comandos úteis (Makefile)

```bash
make up              # Sobe todos os serviços
make down            # Para e remove containers
make logs            # Logs em tempo real
make migrate         # Alembic upgrade head
make shell-backend   # Shell bash no container backend
make test            # pytest
make lint            # ruff check
```

## Desenvolvido como TCC

Este projeto foi desenvolvido como Trabalho de Conclusão de Curso (TCC) intitulado **"Do operador ao Agente: Transformando um atendente de telemarketing em um Agente de Inteligência Artificial Autônomo"**, apresentado à Universidade de São Paulo (USP).

O objetivo acadêmico é demonstrar a viabilidade de substituir fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional e escalar para atendimento humano quando necessário — integrando múltiplos canais de comunicação em uma arquitetura moderna baseada em microsserviços e LLMs.

