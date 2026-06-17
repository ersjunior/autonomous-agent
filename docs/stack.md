# Stack tecnológica

Linguagens, frameworks, bibliotecas e modelos de IA utilizados no projeto.

## Linguagens

| Linguagem | Versão | Onde |
|---|---|---|
| Python | 3.12 | Backend, worker, agentes |
| TypeScript | 5.8 | Frontend |
| Node.js | 22 (CI) | Build/execução do frontend |

## Backend

Framework e bibliotecas principais (`backend/requirements.txt`):

| Biblioteca | Papel |
|---|---|
| FastAPI | Framework web (API REST + WebSocket) |
| Uvicorn | Servidor ASGI |
| SQLAlchemy 2.x | ORM (async) |
| Alembic | Migrations de banco |
| asyncpg | Driver PostgreSQL assíncrono |
| pgvector | Busca vetorial (embeddings) |
| Pydantic 2.x | Validação e schemas |
| Celery | Filas de tarefas assíncronas |
| redis | Cliente Redis |
| LangGraph | Orquestração do grafo de agentes |
| LangChain | Utilidades de LLM |
| twilio | SDK WhatsApp/Voz |
| python-telegram-bot | SDK Telegram |
| pytest | Testes |

## Frontend

| Biblioteca | Papel |
|---|---|
| Next.js 15 | Framework React (App Router) |
| React 19 | UI |
| Tailwind CSS 3 | Estilização |
| Recharts | Gráficos (métricas, funil) |
| lucide-react | Ícones |
| next-themes | Tema claro/escuro |

## Modelos de IA

O sistema é **agnóstico de provedor** e roda a **stack OSS local por padrão**, sem depender de provedores de nuvem nem de chaves de API. Cada camada pode ser plugada a uma alternativa de nuvem (opcional) via variável de ambiente / settings dinâmicas, **sem alteração de código** (`agents/provider_factory.py`).

### Padrão local (stack OSS)

| Função | Provider | Modelo | Detalhe |
|---|---|---|---|
| LLM (chat + saída estruturada) | Ollama | `llama3.1` | GPU recomendada (NVIDIA) |
| Embeddings | Ollama | `nomic-embed-text` | 768 dimensões |
| STT (voz → texto) | faster-whisper | `large-v3` (default) | GPU `cuda`+`float16` por padrão; CPU com `int8` |
| TTS (texto → voz) | Coqui | XTTS-v2 (`multilingual/multi-dataset`) | Síntese em português (`pt`); GPU `cuda` por padrão |

> **`WHISPER_MODEL`:** o default em `config.py` e no `docker-compose.yml` é `large-v3`. O `.env.example` recomenda `large-v3-turbo` (~2x mais rápido, qualidade PT próxima) — basta defini-lo no `.env`. Em CPU limitado, `medium` é uma alternativa.

### Alternativas de nuvem (opcionais)

| Função | Provider | Como ativar |
|---|---|---|
| LLM | OpenAI (`gpt-4o`) | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` |
| STT | OpenAI (Whisper API) | `STT_PROVIDER=openai` + `OPENAI_API_KEY` |
| TTS | ElevenLabs | `TTS_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY` |
| Embeddings | OpenAI (`text-embedding-3-small`) | acompanha `LLM_PROVIDER=openai`; ajuste `EMBEDDING_DIMENSIONS=1536` |

As chaves de nuvem são exigidas **apenas** quando a respectiva alternativa é ativada; no modo local nenhuma chave é necessária.

## Dados e mensageria

| Tecnologia | Uso |
|---|---|
| PostgreSQL 16 + pgvector | Dados relacionais (CRM) e memória vetorial de longo prazo |
| Redis 7 | Histórico de chat (TTL), broker e result backend do Celery, pub/sub de eventos, modo humano, slots de capacidade |

## Infraestrutura

| Tecnologia | Uso |
|---|---|
| Docker + Docker Compose | Orquestração de todos os serviços |
| Cloudflare Tunnel | Exposição pública do backend (webhooks), com URL fixa via named tunnel |
| Twilio | Conectividade WhatsApp e Voz (PSTN) |
| GitHub Actions | CI (testes + build) |

Para detalhes de configuração, veja [configuracao.md](configuracao.md) e [infra.md](infra.md).
