# Arquitetura

Visão geral da arquitetura do Autonomous Agent: serviços, fluxos de mensagem e o pipeline de IA.

## Visão geral

O sistema é um conjunto de microsserviços orquestrados via Docker Compose. Uma mensagem entra por um canal (WhatsApp, Telegram ou Voz), é processada de forma assíncrona por um worker que invoca um grafo de agentes (LangGraph), e a resposta é gerada com apoio de RAG (memória do contato + base de conhecimento) antes de retornar pelo mesmo canal.

A IA é **agnóstica de provedor** e roda a **stack OSS local por padrão** (Ollama, faster-whisper, Coqui), sem chaves de API. Qualquer camada (LLM/STT/TTS/embeddings) pode ser plugada a uma **alternativa de nuvem (opcional)** por variável de ambiente, sem alterar código (`agents/provider_factory.py`).

O agente opera em dois perfis de negócio:

- **ACTIVE (ativo/outbound):** campanhas que disparam mensagens para leads.
- **RECEPTIVE (receptivo/inbound):** resposta a mensagens recebidas, com fila e controle de capacidade.

## Serviços

| Serviço | Imagem/base | Papel |
|---|---|---|
| `backend` | FastAPI (Python 3.12) | API REST, webhooks, WebSocket de monitoramento, migrations e seed no startup |
| `frontend` | Next.js 15 | Dashboard de gestão (agentes, canais, leads, campanhas, etc.) |
| `worker` | Celery | Processamento assíncrono de mensagens inbound e campanhas outbound |
| `celery-beat` | Celery Beat | Agendador (devolutivas, sweeps, scheduler de acionamento, fila receptiva) |
| `postgres` | pgvector/pgvector:pg16 | Banco relacional + extensão pgvector (memória de longo prazo) |
| `redis` | redis:7-alpine | Histórico de chat (TTL), broker/result do Celery, pub/sub de eventos, modo humano, slots de capacidade |
| `ollama` | Ollama | LLM (llama3.1) + embeddings (nomic-embed-text) — GPU NVIDIA recomendada |
| `faster-whisper` | REST :8001 | STT (transcrição de voz) — GPU NVIDIA recomendada |
| `coqui-tts` | REST :8002 | TTS (síntese de voz, XTTS-v2, português) — GPU NVIDIA recomendada |
| `cloudflared` | Cloudflare Tunnel | Expõe o backend publicamente (webhooks Twilio/Telegram) |
| `telegram-polling` | profile `telegram-polling` | Polling do Telegram (serviço separado, opt-in) |

### Seleção de provedor de IA (agnóstico)

A `agents/provider_factory.py` instancia o provider de cada camada a partir de variáveis de ambiente, sem alterar código:

| Camada | Padrão local (OSS) | Alternativa de nuvem (opcional) | Variável |
|---|---|---|---|
| LLM | Ollama `llama3.1` | OpenAI `gpt-4o` | `LLM_PROVIDER` |
| STT | faster-whisper | OpenAI Whisper API | `STT_PROVIDER` |
| TTS | Coqui XTTS-v2 | ElevenLabs | `TTS_PROVIDER` |
| Embeddings | Ollama `nomic-embed-text` (768d) | OpenAI `text-embedding-3-small` (1536d) | acompanha `LLM_PROVIDER` / `EMBEDDING_DIMENSIONS` |

Os serviços `ollama`/`faster-whisper`/`coqui-tts` só são exercitados no modo local; ao ativar uma alternativa de nuvem, a respectiva chave (`OPENAI_API_KEY`/`ELEVENLABS_API_KEY`) passa a ser necessária.

## Fluxo inbound (mensageria)
Cliente → Canal → HTTP/polling → Celery → Worker → Grafo de agentes → Envio da resposta

1. **Recepção:**
   - WhatsApp: `POST /api/v1/channels/webhooks/whatsapp` (Twilio) → dedup no Redis → enfileira tarefa Celery → responde TwiML vazio imediatamente.
   - Telegram (polling): o serviço `telegram-polling` recebe a atualização e enfileira a mesma tarefa.
   - Telegram (webhook): `POST /api/v1/channels/webhooks/telegram`.
2. **Worker** (`worker/tasks/inbound_handler.py`): identifica o lead e resolve o agente (ACTIVE/RECEPTIVE).
3. **Antes do grafo:** se o contato estiver em modo humano, o fluxo é curto-circuitado (a IA não responde). Caso contrário, o indicador "digitando..." é acionado.
4. **Grafo de agentes** (`agents/orchestrator/`): roteamento → identificação de intenção → checagem de escalonamento → geração da resposta (com RAG).
5. **Envio:** a resposta é enviada pela API do canal (não via TwiML com texto), e a interação é registrada.

No perfil RECEPTIVE, o atendimento pode passar por uma **fila receptiva** com controle de capacidade; no ACTIVE com conversa aberta, o atendimento é imediato.

## Fluxo outbound (campanha)

1. `POST /api/v1/campaigns/{id}/start` enfileira as tarefas da campanha.
2. O **scheduler** (Celery Beat, a cada 5 min) respeita janela de horário (fuso de São Paulo), cadência, slots e capacidade global.
3. A tarefa de campanha gera a mensagem pelo grafo (personalidade ACTIVE) e entrega pelo canal:
   - WhatsApp/Telegram: envio direto pela API.
   - Voz: áudio sintetizado (Coqui → MP3) tocado via Twilio (`<Play>`), com fallback para voz padrão Twilio em português (`<Say>` Polly pt-BR).

## Pipeline de IA (RAG em dois níveis)

Durante a geração da resposta, o grafo consulta duas fontes de contexto:

1. **Memória do contato (longo prazo):** busca semântica nas interações passadas daquele usuário (`interactions` + pgvector), isolada por `user_id`.
2. **Base de conhecimento (KB):** trechos de documentos institucionais (`kb_chunks`), filtrados por documentos prontos e escopo do dono.

Além do RAG, o prompt recebe a **identidade institucional** (nome, tom, contexto de negócio), resolvida em duas camadas — workspace + override por agente — e separada da KB (a identidade define *quem* o agente é; a KB guarda os *fatos*). Ver [agentes.md](agentes.md).

A resposta é persistida no histórico de curto prazo (Redis) e indexada no longo prazo (pgvector) para enriquecer conversas futuras.

## Exposição pública (túnel Cloudflare)

Para receber webhooks (Twilio e Telegram em modo webhook), o backend precisa ser acessível publicamente. O serviço `cloudflared` provê isso em dois modos: `temporary` (quick tunnel com URL `*.trycloudflare.com` aleatória) e `named` (URL fixa em domínio próprio, recomendado). Detalhes em [infra.md](infra.md).

## Memória

| Tipo | Implementação | Uso |
|---|---|---|
| Curto prazo | Redis (`chat:{user_id}`, TTL 1h) | Histórico imediato da conversa |
| Longo prazo | PostgreSQL + pgvector (`interactions.embedding`) | Memória semântica por contato |
| Eventos | Redis pub/sub (`agent_events`) | Feed em tempo real do dashboard |

## Diagrama (alto nível)
┌──────────┐   webhook/polling   ┌─────────┐   enfileira   ┌────────┐

│  Canais  │ ──────────────────► │ Backend │ ────────────► │ Redis  │

│ TG/WA/Voz│                     │ FastAPI │               │ broker │

└────▲─────┘                     └─────────┘               └───┬────┘

│                                                         │

│ resposta                                          consome│

│                                                         ▼

│                          ┌──────────┐   grafo    ┌────────────┐

└──────────────────────────│  Worker  │ ─────────► │  LangGraph │

│  Celery  │            │  + RAG     │

└──────────┘            └─────┬──────┘

│

┌───────────────┴────────────┐

▼                            ▼

┌────────────┐              ┌──────────────┐

│ PostgreSQL │              │   Ollama     │

│ + pgvector │              │ LLM + embed  │

└────────────┘              └──────────────┘

Para detalhes de cada parte, veja [backend.md](backend.md), [canais.md](canais.md), [agentes.md](agentes.md) e [infra.md](infra.md).
