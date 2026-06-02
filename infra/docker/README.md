# Docker

Configurações Docker Compose para ambientes local (dev) e produção.

## Arquivos

| Arquivo | Uso |
|---------|-----|
| `docker-compose.yml` | Base — postgres, redis, backend, frontend, worker + serviços OSS |
| `docker-compose.dev.yml` | Override DEV — worker com loglevel debug |
| `docker-compose.prod.yml` | Override PRD — sem volumes, frontend standalone, workers |
| `postgres/init.sql` | Habilita extensão `vector` (pgvector) na inicialização |
| `faster-whisper/` | STT local (profile `opensource`) — Dockerfile + app FastAPI |
| `coqui-tts/` | TTS local XTTS-v2 (profile `opensource`) — Dockerfile + app FastAPI |
| `coqui-tts/voices/` | WAV de referência para clonagem de voz (montado em `/voices`, somente leitura) |

## Comandos (a partir da raiz do projeto)

```bash
make up                # DEV
make prod-up           # PRD
make down              # parar DEV
make prod-down         # parar PRD
make setup-opensource  # stack 100% local (Ollama + faster-whisper + Coqui)
```

Antes de subir, copie `.env.example` para `.env` e ajuste `DEBUG` e `SECRET_KEY`.

## Stack open source (100% local)

Os serviços `ollama`, `faster-whisper` e `coqui-tts` têm `profiles: [opensource]` e só sobem
quando o profile é ativado. O Makefile expõe targets dedicados que usam `.env.local`
(com `LLM_PROVIDER=ollama`, `STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui`,
`EMBEDDING_DIMENSIONS=768`):

```bash
make setup-opensource    # up + pull-models + opensource-migrate
make opensource-up       # apenas sobe a stack opensource
make opensource-logs     # logs
make opensource-down     # para a stack
```

O serviço `coqui-tts` monta `coqui-tts/voices/` como bind mount somente leitura em `/voices`.
Coloque o `reference.wav` nessa pasta antes de subir (os `.wav` são ignorados pelo Git).
O `coqui-tts` transcodifica a saída para MP3 (`audio/mpeg`) via ffmpeg, igual ao ElevenLabs.

Os três serviços OSS (`ollama`, `faster-whisper`, `coqui-tts`) têm `healthcheck` definido,
e `opensource-up` sobe com `--wait` — o `setup-opensource` só baixa modelos e migra depois
que todos reportam *healthy* (sem `sleep` cego).

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
