# Autonomous Agent

[![Licença: MIT](https://img.shields.io/badge/Licença-MIT-blue.svg)](LICENSE)

Sistema multi-agente de inteligência artificial para atendimento autônomo de clientes em múltiplos canais (WhatsApp, Telegram, voz e vídeo). O agente opera em modo **ativo** (campanhas outbound para leads) ou **receptivo** (resposta a mensagens recebidas), orquestrado com LangGraph e provedores configuráveis de LLM, STT, TTS e avatar (OpenAI/ElevenLabs/D-ID ou stack open source via Ollama, faster-whisper e Coqui).

## Arquitetura

O projeto é composto pelos seguintes serviços:

| Serviço    | Função |
|------------|--------|
| **Backend** | API REST FastAPI — autenticação, CRUD, webhooks e WebSocket de monitoramento |
| **Frontend** | Dashboard Next.js 15 para gestão de agentes, canais, leads e campanhas |
| **Worker** | Celery — processamento assíncrono de mensagens inbound e campanhas outbound |
| **PostgreSQL** | Banco relacional com extensão pgvector para memória de longo prazo |
| **Redis** | Cache de conversas (TTL), broker Celery, pub/sub de eventos em tempo real |
| **Ollama** *(padrão)* | LLM e embeddings locais (sobe sempre) |
| **faster-whisper** *(padrão)* | STT local (sobe sempre) |
| **Coqui TTS** *(padrão)* | TTS local XTTS-v2 (sobe sempre) |

Fluxo resumido: mensagens entram via webhook ou campanha → Worker ou Backend delega ao grafo LangGraph em `agents/` → intent + resposta → envio pelo canal → eventos publicados no Redis → dashboard consome via WebSocket.

## Provedores de IA

A camada de IA usa o padrão **ProviderFactory** (`agents/provider_factory.py`): a implementação concreta é escolhida via variáveis de ambiente, sem alterar o grafo LangGraph.

Por padrão o projeto roda **100% open source** — LLM, STT e TTS locais, sem nenhuma chave paga (coluna marcada com ★).

| Camada | Variável | Open source | Comercial |
|--------|----------|-------------|-----------|
| LLM + embeddings | `LLM_PROVIDER` | ★ `ollama` (llama3.1) | `openai` (GPT-4o) |
| STT | `STT_PROVIDER` | ★ `faster_whisper` | `openai` (Whisper) |
| TTS | `TTS_PROVIDER` | ★ `coqui` | `elevenlabs` |
| Avatar | `AVATAR_PROVIDER` | `sadtalker` | ★ `did` |

> ★ = valor padrão. O avatar em vídeo continua usando `did` por padrão (defina `AVATAR_PROVIDER=sadtalker` para a alternativa local).

### Stack 100% local (open source) — padrão

A stack open source (Ollama + faster-whisper + Coqui) é o **modo padrão**: os serviços
sobem sempre com `make up`, e o `.env.example` já vem com `LLM_PROVIDER=ollama`,
`STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui` e `EMBEDDING_DIMENSIONS=768`. O comando
de primeira inicialização recomendado é:

```bash
make setup   # sobe a stack, baixa os modelos do Ollama e aplica as migrations
```

Equivale a, em sequência: `make up` → aguardar o Ollama → `make pull-models` → `make warm-ollama` → `make migrate`.

> O Coqui XTTS-v2 exige um WAV de referência para clonagem de voz. Coloque o arquivo em
> `infra/docker/coqui-tts/voices/reference.wav` — essa pasta é montada no container como
> bind mount somente leitura (`/voices`). Os `.wav` dessa pasta são ignorados pelo Git.

Os targets `opensource-*` continuam disponíveis para rodar a stack open source de forma
isolada com um `.env.local` dedicado:

```bash
make setup-opensource     # one-shot com .env.local (sobe + modelos + migrations)
make opensource-up        # sobe a stack (usa .env.local)
make opensource-down      # para a stack opensource
make opensource-logs      # logs em tempo real
make pull-models          # baixa llama3.1 + nomic-embed-text no container Ollama
make opensource-migrate   # alembic upgrade head dentro do backend (usa .env.local)
```

Para usar OpenAI/ElevenLabs, troque os providers no `.env` (ver [Caminho B](#2b-caminho-comercial-opcional-openai--elevenlabs--d-id)) e ajuste `EMBEDDING_DIMENSIONS=1536` antes de rodar `make migrate` — a migration `alter_interactions_embedding_dimensions` adapta a coluna pgvector automaticamente.

Documentação de fine-tuning: [`docs/fine-tuning/`](docs/fine-tuning/).

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose v2
- [Python 3.12](https://www.python.org/downloads/) (desenvolvimento local opcional)
- [Node.js 20+](https://nodejs.org/) (desenvolvimento local do frontend opcional)

## Instalação

O projeto pode rodar de **duas formas**, e você escolhe sem editar código — apenas variáveis de ambiente:

| Caminho | Quando usar | Requer chaves pagas? |
|---------|-------------|:--------------------:|
| **100% local / open source** (Ollama + faster-whisper + Coqui) — **padrão** | Sem custo de API, dados não saem da máquina | Não |
| **Comercial** (OpenAI + ElevenLabs + D-ID) | Melhor qualidade, setup rápido | Sim (`OPENAI_API_KEY`, etc.) |

Siga o passo **2A** (open source, padrão) **ou** **2B** (comercial). Os demais passos são comuns.

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/autonomous-agent.git
cd autonomous-agent
```

### 2A. Caminho 100% local (open source) — padrão

Não precisa de nenhuma chave paga. O `.env.example` já vem configurado para a stack open
source (`LLM_PROVIDER=ollama`, `STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui`,
`EMBEDDING_DIMENSIONS=768`):

```bash
cp .env.example .env
```

Um único comando sobe a stack, baixa os modelos do Ollama e aplica as migrations:

```bash
make setup
```

> O TTS local (Coqui XTTS-v2) exige um WAV de referência para clonagem de voz. Antes de
> rodar, coloque o arquivo em `infra/docker/coqui-tts/voices/reference.wav` (a pasta é
> montada no container como `/voices`, somente leitura; os `.wav` são ignorados pelo Git).

Os serviços Ollama, faster-whisper e Coqui sobem automaticamente junto com `make up`.
O backend executa `alembic upgrade head` no startup (schema via migrations); `make setup`
também chama `make migrate` para garantir o banco no `head` após o primeiro pull dos modelos.

Se as portas **8001** ou **8002** do host estiverem ocupadas por outros projetos, ajuste no
`.env`: `WHISPER_PORT=18001` e `COQUI_PORT=18002` (as URLs internas entre containers não mudam).

### 2B. Caminho comercial (opcional: OpenAI / ElevenLabs / D-ID)

```bash
cp .env.example .env
```

Edite o `.env`, troque os providers para os comerciais e preencha as credenciais dos
serviços que vai usar:

```env
LLM_PROVIDER=openai
STT_PROVIDER=openai
TTS_PROVIDER=elevenlabs
EMBEDDING_DIMENSIONS=1536
OPENAI_API_KEY=sk-...
```

Chaves principais:

| Variável | Desenvolvimento | Produção |
|----------|-----------------|----------|
| `DEBUG` | `true` | `false` |
| `SECRET_KEY` | qualquer valor para testes | chave forte e aleatória (mín. 32 caracteres) |
| `OPENAI_API_KEY` | obrigatória se `LLM_PROVIDER=openai` | obrigatória se `LLM_PROVIDER=openai` |

Suba a stack:

```bash
make up        # DEV (hot-reload, volumes montados; migrations no startup do backend)
# ou
make prod-up   # PRD (imagens baked, DB/Redis sem portas expostas)
```

Se precisar reaplicar migrations manualmente (ex.: após trocar `EMBEDDING_DIMENSIONS`):

```bash
make migrate
```

### 3. Notas comuns de ambiente

**Importante:** dentro dos containers Docker, `DATABASE_URL` e `REDIS_URL` usam os hostnames `postgres` e `redis` (definidos automaticamente no Compose). Os valores `localhost` no `.env`/`.env.local` servem para acesso **fora** do Docker (migrations locais, DBeaver, etc.).

**Compose e `.env`:** prefira `make up` / `make setup`. Se usar `docker compose` direto, **sempre** passe `--env-file .env` — sem isso o Compose não lê o `.env` da raiz e pode falhar ao publicar portas `8001`/`8002` já ocupadas no host.

Equivalente manual ao `make up`/`make prod-up`:

```bash
# DEV
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d --build

# PRD
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.prod.yml up -d --build
```

### 4. Acessar a aplicação

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

### Provedores de IA

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `LLM_PROVIDER` | `openai` ou `ollama` | `ollama` |
| `STT_PROVIDER` | `openai` ou `faster_whisper` | `faster_whisper` |
| `TTS_PROVIDER` | `elevenlabs` ou `coqui` | `coqui` |
| `AVATAR_PROVIDER` | `did` ou `sadtalker` | `did` |
| `EMBEDDING_DIMENSIONS` | Dimensão do vetor pgvector (`1536` OpenAI, `768` Ollama) | `768` |

### Integrações — comercial

| Variável | Descrição | Obrigatória |
|----------|-----------|:-----------:|
| `OPENAI_API_KEY` | API OpenAI (GPT-4o + Whisper) | Opcional — só se `LLM_PROVIDER=openai` ou `STT_PROVIDER=openai` |
| `OPENAI_MODEL` | Modelo LLM (padrão: `gpt-4o`) | Opcional — só se `LLM_PROVIDER=openai` |
| `TWILIO_ACCOUNT_SID` | Twilio — WhatsApp e voz | Canal WhatsApp/Voz |
| `TWILIO_AUTH_TOKEN` | Token Twilio | Canal WhatsApp/Voz |
| `TWILIO_PHONE_NUMBER` | Número Twilio | Canal WhatsApp/Voz |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram | Canal Telegram |
| `ELEVENLABS_API_KEY` | TTS ElevenLabs | Se `TTS_PROVIDER=elevenlabs` |
| `ELEVENLABS_VOICE_ID` | ID da voz ElevenLabs | Se `TTS_PROVIDER=elevenlabs` |
| `DID_API_KEY` | D-ID avatar em vídeo | Se `AVATAR_PROVIDER=did` |

### Integrações — open source

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `OLLAMA_BASE_URL` | URL do Ollama | `http://ollama:11434` |
| `OLLAMA_MODEL` | Modelo Ollama | `llama3.1` |
| `OLLAMA_PORT` | Porta exposta no host | `11434` |
| `OLLAMA_KEEP_ALIVE` | Tempo que o modelo fica carregado em memória (`24h`, `-1` = infinito, `0` = descarrega já) | `24h` |
| `WHISPER_BASE_URL` | URL do faster-whisper | `http://faster-whisper:8001` |
| `WHISPER_MODEL` | Modelo Whisper | `large-v3` |
| `WHISPER_PORT` | Porta exposta no host (remapeie se `8001` estiver ocupada, ex.: `18001`) | `8001` |
| `WHISPER_DEVICE` | Dispositivo faster-whisper (`cpu` / `cuda`) | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Tipo de compute (`int8`, `float16`, …) | `int8` |
| `COQUI_BASE_URL` | URL do Coqui TTS | `http://coqui-tts:8002` |
| `COQUI_MODEL` | Modelo Coqui XTTS-v2 | `tts_models/multilingual/multi-dataset/xtts_v2` |
| `COQUI_VOICE_SAMPLE` | Caminho do WAV de referência (dentro do container) | `/voices/reference.wav` |
| `COQUI_PORT` | Porta exposta no host (remapeie se `8002` estiver ocupada, ex.: `18002`) | `8002` |
| `SADTALKER_BASE_URL` | URL do SadTalker | `http://sadtalker:8003` |

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
│   ├── providers/       # LLM, STT, TTS, Avatar (OpenAI, Ollama, Coqui, etc.)
│   ├── workers/         # Intent e response agents
│   ├── memory/          # Redis (curto prazo) + pgvector (longo prazo)
│   ├── tools/           # CRM, calendário, base de conhecimento
│   ├── provider_factory.py  # Seleção de provedor via env
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
├── infra/docker/        # docker-compose.yml + overrides dev/prod + serviços OSS
├── tests/               # Testes automatizados
└── docs/                # Documentação adicional
    └── fine-tuning/     # Guias LLM, STT e TTS
```

## Comandos úteis (Makefile)

### Desenvolvimento

```bash
make setup           # ⭐ Primeira inicialização: sobe + baixa modelos Ollama + migrations
make up              # Sobe stack DEV (build + hot-reload)
make down            # Para containers DEV
make logs            # Logs em tempo real
make migrate         # Alembic upgrade head
make shell-backend   # Shell bash no container backend
make test            # pytest
make lint            # ruff check
```

> Use `make setup` na primeira subida: equivale ao antigo `setup-opensource`, mas para o
> fluxo padrão (`.env` + stack DEV). Ele sobe os serviços, aguarda o Ollama, baixa os
> modelos (`llama3.1` + `nomic-embed-text`), aquece o modelo e aplica as migrations.
> O backend também migra automaticamente no startup (`alembic upgrade head`).

### Produção

```bash
make prod-up         # Sobe stack PRD (sem volumes de código)
make prod-down       # Para containers PRD
make prod-logs       # Logs da stack PRD
```

### Stack open source (100% local)

```bash
make setup-opensource    # Sobe + baixa modelos Ollama + migrations (one-shot)
make opensource-up       # Sobe a stack opensource (usa .env.local)
make opensource-down     # Para a stack opensource
make opensource-logs     # Logs da stack opensource
make pull-models         # Baixa llama3.1 + nomic-embed-text no Ollama
make opensource-migrate  # Alembic upgrade head (usa .env.local)
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
├── docker-compose.prod.yml  # override PRD
├── faster-whisper/          # STT local (sobe sempre)
├── coqui-tts/               # TTS local (sobe sempre)
│   └── voices/              # WAV de referência (bind mount /voices, *.wav ignorado no Git)
└── postgres/init.sql        # extensão pgvector no init
```

Os serviços de IA local (Ollama, faster-whisper, Coqui) sobem **sempre** junto com a stack — são o modo padrão do projeto. Os targets `opensource-*` do Makefile (com `.env.local`) continuam disponíveis para um fluxo isolado alternativo.

## CI/CD

| Workflow | Gatilho | Requerido |
|---|---|---|
| `ci.yml` | Push em `main`/`develop` | Automático |
| `docker-publish.yml` | Tag `v*` | Requer secrets |

### Publicação de imagens Docker (opcional)

Para habilitar a publicação automática no Docker Hub ao criar uma release:

1. Crie uma conta em [hub.docker.com](https://hub.docker.com)
2. Gere um token em **Account Settings → Security → New Access Token**
3. Adicione em **Settings → Secrets → Actions** do repositório:
   - `DOCKER_USERNAME` — seu usuário Docker Hub
   - `DOCKER_TOKEN` — o token gerado

> Sem esses secrets, o workflow exibe um aviso informativo e
> o deploy local via `make up` continua funcionando normalmente.

## Desenvolvido como TCC

Este projeto foi desenvolvido como Trabalho de Conclusão de Curso (TCC) intitulado **"Do operador ao Agente: Transformando um atendente de telemarketing em um Agente de Inteligência Artificial Autônomo"**, apresentado ao **ICMC** (Instituto de Ciências Matemáticas e de Computação) da **USP** (Universidade de São Paulo).

O objetivo acadêmico é demonstrar a viabilidade de substituir fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional e escalar para atendimento humano quando necessário — integrando múltiplos canais de comunicação em uma arquitetura moderna baseada em microsserviços e LLMs.
