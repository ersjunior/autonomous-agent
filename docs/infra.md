# Infraestrutura e deploy

Orquestração via Docker Compose, exposição pública por túnel Cloudflare e automação por Makefile.

## Docker Compose

A stack é definida em três arquivos compostos:

| Arquivo | Função |
|---|---|
| `infra/docker/docker-compose.yml` | Stack base (todos os serviços + profile `telegram-polling`) |
| `infra/docker/docker-compose.dev.yml` | Override de desenvolvimento (worker em modo debug, bind mounts) |
| `infra/docker/docker-compose.prod.yml` | Override de produção (sem bind mounts, múltiplos workers, portas de banco/Redis fechadas) |

O ambiente de desenvolvimento combina base + dev; o de produção combina base + prod.

### Portas expostas (host → container)

| Serviço | Host | Container |
|---|---|---|
| PostgreSQL | 25432 | 5432 |
| Redis | 16379 | 6379 |
| Backend | 8000 | 8000 |
| Frontend | 3000 | 3000 |
| faster-whisper | — | 8001 |
| coqui-tts | — | 8002 |

## Túnel Cloudflare

O backend precisa estar acessível publicamente para receber webhooks (Twilio e Telegram). Isso é feito por um túnel Cloudflare, com dois modos (via `TUNNEL_MODE`):

| Modo | Como funciona | Quando usar |
|---|---|---|
| `temporary` | Quick tunnel; gera uma URL `*.trycloudflare.com` aleatória a cada execução, gravada em arquivo para o backend ler | Testes rápidos, sem domínio próprio |
| `named` | Túnel nomeado, autenticado por `CLOUDFLARE_TUNNEL_TOKEN`, com URL fixa via `PUBLIC_BASE_URL` (domínio próprio) | Uso estável; a URL não muda entre reinícios |

O `entrypoint.sh` (`infra/docker/cloudflared/`) decide o modo. No modo `named`, a flag de execução do cloudflared é posicionada para conectar de forma estável e a URL pública vem fixa do `.env`. A resolução da URL pública no backend (`app/core/config.py`) prioriza `PUBLIC_BASE_URL` quando definida.

> O modo `named` é o recomendado para demonstrações: como a URL é fixa, o webhook configurado na Twilio nunca precisa ser reajustado após reinícios.

## Makefile

Atalhos para as operações comuns (todos usam o Compose de desenvolvimento por padrão):

| Alvo | Ação |
|---|---|
| `make up` | Sobe a stack (`up -d --build`) |
| `make down` | Para e remove os containers |
| `make logs` | Logs em tempo real |
| `make setup` | Sobe + espera o Ollama + baixa modelos + aquece + aplica migrations |
| `make migrate` | Aplica as migrations (Alembic) |
| `make pull-models` | Baixa os modelos do Ollama (`llama3.1`, `nomic-embed-text`) |
| `make warm-ollama` | Pré-carrega o modelo na memória |
| `make shell-backend` | Abre um shell no container do backend |
| `make test` | Testes unitários |
| `make test-integration` | Testes de integração (com Postgres de teste) |
| `make lint` | Lint (ruff) em backend/agents/worker |
| `make prod-up` / `prod-down` / `prod-logs` | Operações na stack de produção |
| `make opensource-*` | Variantes usando `.env.local` |

O `make setup` é o caminho recomendado para subir do zero, pois garante que os modelos de IA estejam baixados e o banco migrado. O serviço `telegram-polling` (profile separado) precisa ser subido manualmente quando o Telegram for usado em modo polling.

## Tarefas agendadas (Celery Beat)

| Tarefa | Intervalo | Função |
|---|---|---|
| `gerar-devolutivas-diarias` | 00:00 UTC | Gera devolutiva (Excel) das bases |
| `marcar-nao-atendidos` | a cada hora | Sweep de status |
| `limpar-audios-voz` | 03:00 UTC | Limpeza de MP3 de voz |
| `process-active-activations` | a cada 5 min | Scheduler de campanhas outbound |
| `process-receptive-queue` | ~30s | Processa a fila receptiva |
| `sweep-queue-abandonment` | a cada 2 min | Abandono de fila (voz) |
| `sweep-human-handoff-timeouts` | ~60s | Devolve ao bot atendimentos em modo humano inativos |

## CI (GitHub Actions)

| Job | O que faz |
|---|---|
| `backend-tests` | Python 3.12 + testes unitários |
| `backend-integration` | Postgres (pgvector) + Redis + testes de integração e de API |
| `frontend-build` | Node 22 + build do Next.js |

Para variáveis de ambiente, veja [configuracao.md](configuracao.md). Para os testes, veja [testes.md](testes.md).
