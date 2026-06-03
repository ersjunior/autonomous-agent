# Docker

Configurações Docker Compose para ambientes local (dev) e produção.

## Arquivos

| Arquivo | Uso |
|---------|-----|
| `docker-compose.yml` | Base — postgres, redis, backend, frontend, worker + Ollama, faster-whisper, Coqui |
| `docker-compose.dev.yml` | Override DEV — worker com loglevel debug |
| `docker-compose.prod.yml` | Override PRD — sem volumes, frontend standalone, workers |
| `postgres/init.sql` | Habilita extensão `vector` (pgvector) na inicialização |
| `faster-whisper/` | STT local — Dockerfile + app FastAPI (sobe sempre) |
| `coqui-tts/` | TTS local XTTS-v2 — Dockerfile Python 3.11 + app FastAPI (sobe sempre) |
| `coqui-tts/voices/` | WAV de referência para clonagem de voz (montado em `/voices`, somente leitura) |

## Comandos (a partir da raiz do projeto)

```bash
cp .env.example .env    # primeira vez — ajuste DEBUG, SECRET_KEY e portas se necessário
make setup              # 1ª subida: up + modelos Ollama + warm-up + migrate
make up                 # sobe stack DEV (já injeta --env-file .env + override dev)
make down               # para DEV
make prod-up            # PRD
make migrate            # alembic upgrade head (idempotente; o backend também migra no startup)
```

> **Importante:** use sempre `make up` ou inclua `--env-file .env` ao chamar o Compose manualmente.
> O comando `docker compose -f infra/docker/docker-compose.yml up` **sem** `--env-file` não lê o `.env`
> da raiz (o Compose procura o arquivo no diretório do compose) e pode falhar por conflito de porta
> ou providers incorretos.

## Stack open source (padrão)

Os serviços `ollama`, `faster-whisper` e `coqui-tts` **sobem sempre** com a stack — não há mais
`profiles: [opensource]` no compose base. O `.env.example` já define `LLM_PROVIDER=ollama`,
`STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui` e `EMBEDDING_DIMENSIONS=768`.

O `make setup` (fluxo padrão com `.env`):

1. Sobe todos os containers (`make up`)
2. Aguarda o Ollama (`wait-ollama` — polling, até 5 min)
3. Baixa `llama3.1` + `nomic-embed-text` (`pull-models`)
4. Pré-aquece o modelo (`warm-ollama`)
5. Aplica migrations (`make migrate`)

O backend também executa `alembic upgrade head` automaticamente no startup — migrations são a
fonte única do schema (não há mais `create_all` no lifespan).

### Coqui TTS

- Coloque `reference.wav` em `coqui-tts/voices/` antes de usar TTS (bind mount `/voices`, `*.wav` ignorados pelo Git).
- Imagem base: **Python 3.11** (o pacote Coqui `TTS` não publica wheels para 3.12).
- Saída transcodificada para MP3 (`audio/mpeg`) via ffmpeg, compatível com Twilio/ElevenLabs.

### Ollama

- `OLLAMA_KEEP_ALIVE` (padrão `24h`) evita descarregar o modelo por inatividade.
- `warm-ollama` dispara inferência após o pull para reduzir cold start na primeira requisição real.

### Portas no host (conflitos)

As portas publicadas no host de Whisper e Coqui são parametrizáveis via `.env`:

| Variável | Padrão no `.env.example` | Porta interna do container |
|----------|--------------------------|----------------------------|
| `WHISPER_PORT` | `8001` | `8001` |
| `COQUI_PORT` | `8002` | `8002` |

Se `8001` ou `8002` já estiverem em uso no host (outros projetos Docker), remapeie no `.env`
(ex.: `18001`, `18002`). As URLs **dentro** da rede Docker (`http://faster-whisper:8001`,
`http://coqui-tts:8002`) não mudam.

Testes diretos no host usam a porta mapeada: `curl http://localhost:${WHISPER_PORT}/health`.

## Fluxo alternativo: `opensource-*` (`.env.local`)

Targets do Makefile para rodar com `.env.local` dedicado (útil para isolar credenciais locais):

```bash
make setup-opensource    # opensource-up + pull-models + warm-ollama + opensource-migrate
make opensource-up
make opensource-down
make opensource-logs
```

## Portas padrão (DEV)

| Serviço | Porta no host (padrão `.env.example`) |
|---------|----------------------------------------|
| Backend | 8000 |
| Frontend | 3000 |
| PostgreSQL | 25432 |
| Redis | 16379 |
| Ollama | 11434 |
| faster-whisper | `WHISPER_PORT` (8001) |
| Coqui TTS | `COQUI_PORT` (8002) |

## Serviços

- **backend** e **worker** compartilham `backend/Dockerfile` (inclui `agents/` e `worker/`)
- **backend** e **worker** dependem de `ollama`, `faster-whisper` e `coqui-tts` (`service_started`)
- **frontend** usa multi-stage: `dev` (hot-reload) ou `runner` (produção standalone)
- Variáveis de app: `../../.env` via `env_file` no compose + `--env-file .env` no Makefile
