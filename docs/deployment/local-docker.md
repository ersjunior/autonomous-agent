# Deploy Local com Docker

Guia para subir o ambiente de desenvolvimento com Docker Compose na raiz do repositório.

## Pré-requisitos

- Docker Desktop (ou Docker Engine + Compose v2)
- ~8 GB de RAM livres recomendados (Ollama + faster-whisper + Coqui)
- Espaço em disco: ~5 GB para modelos Ollama (`llama3.1` + `nomic-embed-text`)

## Primeira inicialização (recomendado)

```bash
git clone <repo-url> autonomous-agent
cd autonomous-agent
cp .env.example .env
# Opcional: ajuste WHISPER_PORT/COQUI_PORT se 8001/8002 estiverem ocupadas no host
make setup
```

O `make setup` executa, em sequência:

1. `make up` — build + sobe postgres, redis, ollama, faster-whisper, coqui-tts, backend, frontend, worker
2. Aguarda o Ollama responder
3. Baixa modelos (`llama3.1`, `nomic-embed-text`)
4. Pré-aquece o LLM (`warm-ollama`)
5. `make migrate` — Alembic até `head`

O backend **também** roda `alembic upgrade head` no startup; `make migrate` é redundante mas útil após alterar migrations manualmente.

## Subidas seguintes

```bash
make up      # sobe/atualiza containers
make down    # para a stack
make logs    # logs em tempo real
```

## Comando manual equivalente

O Makefile sempre passa `--env-file .env` e o override de dev:

```bash
docker compose --env-file .env \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.dev.yml \
  up -d --build
```

> Não omita `--env-file .env`. Sem ele, o Compose não lê o `.env` da raiz e pode usar portas
> padrão do compose (`8001`/`8002`) que conflitam com outros containers no host.

## Coqui — voz de referência

Antes de usar TTS local, coloque um WAV em:

`infra/docker/coqui-tts/voices/reference.wav`

Configure no `.env`:

```env
TTS_PROVIDER=coqui
COQUI_VOICE_SAMPLE=/voices/reference.wav
```

## URLs locais

| Recurso | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API / Swagger | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Ollama (host) | http://localhost:11434 |
| faster-whisper (host) | http://localhost:${WHISPER_PORT}/health |
| Coqui TTS (host) | http://localhost:${COQUI_PORT}/health |

Admin padrão (seed): `admin@admin.com` / `admin` — altere antes de produção.

## Alternativa de nuvem (opcional)

Para plugar uma alternativa de nuvem (sem alterar código), edite `.env`:

```env
LLM_PROVIDER=openai
STT_PROVIDER=openai
TTS_PROVIDER=elevenlabs
EMBEDDING_DIMENSIONS=1536
OPENAI_API_KEY=sk-...
```

Depois `make up` e `make migrate` (ou reinicie o backend para aplicar migrations no startup).

## Produção local (teste)

```bash
make prod-up
make prod-down
```

Ver também: [README principal](../../README.md), [infra/docker/README.md](../../infra/docker/README.md).
