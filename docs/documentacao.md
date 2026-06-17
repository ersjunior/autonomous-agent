# Documentação — Autonomous Agent

Documento consolidado e auto-contido do projeto. Reúne, em ordem de relevância, todas as partes do sistema. Cada seção também existe como documento dedicado em `docs/`, mas aqui o conteúdo está completo.

> **Resumo:** sistema multi-agente de IA para atendimento autônomo omnichannel (WhatsApp, Telegram e Voz), **agnóstico de provedor** e com a **stack OSS local por padrão** (sem chaves de API), orquestração por grafo (LangGraph), memória de curto e longo prazo, RAG e dashboard de gestão. Desenvolvido como TCC (ICMC-USP).

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Arquitetura](#2-arquitetura)
3. [Canais](#3-canais)
4. [Agentes e orquestração](#4-agentes-e-orquestração)
5. [Backend](#5-backend)
6. [Frontend](#6-frontend)
7. [Stack tecnológica](#7-stack-tecnológica)
8. [Infraestrutura e deploy](#8-infraestrutura-e-deploy)
9. [Configuração](#9-configuração)
10. [Testes](#10-testes)
11. [Scripts de validação](#11-scripts-de-validação)
12. [Roadmap e pendências](#12-roadmap-e-pendências)
13. [Sobre o projeto (TCC)](#13-sobre-o-projeto-tcc)

---

## 1. Visão geral

O Autonomous Agent é uma plataforma que substitui fluxos tradicionais de telemarketing por um agente de IA autônomo. Ele identifica intenções, mantém contexto conversacional, consulta uma base de conhecimento e escala para humano quando necessário, atendendo por **WhatsApp, Telegram e Voz**.

Opera em dois perfis de negócio:

- **ACTIVE (ativo/outbound):** campanhas que disparam mensagens para leads.
- **RECEPTIVE (receptivo/inbound):** atendimento de mensagens recebidas, com fila e controle de capacidade.

O diferencial técnico é ser **agnóstico de provedor**: a **stack OSS local é o padrão** (Ollama, faster-whisper, Coqui), sem chaves de API nem custo de inferência. Cada camada (LLM/STT/TTS/embeddings) pode ser plugada a uma **alternativa de nuvem (opcional)** por variável de ambiente, sem alterar código (`agents/provider_factory.py`).

---

## 2. Arquitetura

O sistema é um conjunto de microsserviços orquestrados via Docker Compose. Uma mensagem entra por um canal, é enfileirada e processada de forma assíncrona por um worker que invoca o grafo de agentes; a resposta é gerada com apoio de RAG e retorna pelo mesmo canal.

### Serviços

| Serviço | Base | Papel |
|---|---|---|
| `backend` | FastAPI (Python 3.12) | API REST, webhooks, WebSocket de monitoramento, migrations e seed no startup |
| `frontend` | Next.js 15 | Dashboard de gestão |
| `worker` | Celery | Processamento assíncrono de inbound e campanhas outbound |
| `celery-beat` | Celery Beat | Agendador (devolutivas, sweeps, scheduler, fila receptiva) |
| `postgres` | pgvector/pgvector:pg16 | Banco relacional + pgvector (memória de longo prazo) |
| `redis` | redis:7-alpine | Histórico de chat (TTL), broker/result do Celery, pub/sub, modo humano, slots |
| `ollama` | Ollama | LLM (llama3.1) + embeddings (nomic-embed-text) |
| `faster-whisper` | REST :8001 | STT |
| `coqui-tts` | REST :8002 | TTS (XTTS-v2, português) |
| `cloudflared` | Cloudflare Tunnel | Exposição pública do backend (webhooks) |
| `telegram-polling` | profile `telegram-polling` | Polling do Telegram (opt-in) |

### Fluxo inbound
Cliente → Canal → HTTP/polling → Celery → Worker → Grafo de agentes → Envio da resposta

1. **Recepção:** WhatsApp via `POST /api/v1/channels/webhooks/whatsapp` (com deduplicação no Redis, resposta TwiML vazia imediata); Telegram via polling (serviço dedicado) ou webhook.
2. **Worker** identifica o lead e resolve o agente (ACTIVE/RECEPTIVE).
3. **Antes do grafo:** se o contato está em modo humano, o fluxo é curto-circuitado; senão, o indicador "digitando..." é acionado.
4. **Grafo:** roteamento → intenção → escalonamento → resposta (com RAG).
5. **Envio:** a resposta sai pela API do canal e a interação é registrada.

No perfil RECEPTIVE, o atendimento pode passar por uma fila com controle de capacidade; no ACTIVE com conversa aberta, é imediato.

### Fluxo outbound

1. `POST /api/v1/campaigns/{id}/start` enfileira as tarefas.
2. O scheduler (Beat, a cada 5 min) respeita janela de horário (fuso de São Paulo), cadência, slots e capacidade global.
3. A tarefa gera a mensagem pelo grafo (personalidade ACTIVE) e entrega pelo canal — para voz, o áudio é sintetizado (Coqui → MP3) e tocado via Twilio (`<Play>`), com fallback `<Say>` Polly pt-BR.

### Pipeline de IA (RAG em dois níveis)

Na geração da resposta, o grafo consulta duas fontes:

1. **Memória do contato (longo prazo):** busca semântica nas interações passadas do usuário (`interactions` + pgvector), isolada por `user_id`.
2. **Base de conhecimento (KB):** trechos de documentos institucionais (`kb_chunks`), filtrados por documentos prontos e escopo do dono.

A resposta é persistida no histórico de curto prazo (Redis) e indexada no longo prazo (pgvector).

### Memória

| Tipo | Implementação | Uso |
|---|---|---|
| Curto prazo | Redis (`chat:{user_id}`, TTL 1h) | Histórico imediato |
| Longo prazo | PostgreSQL + pgvector (`interactions`) | Memória semântica por contato |
| Eventos | Redis pub/sub (`agent_events`) | Feed em tempo real do dashboard |

---

## 3. Canais

Três canais, cada um com inbound, outbound e indicador de "digitando...". Representados pelo enum `ChannelType` (`WHATSAPP`, `TELEGRAM`, `VOICE`); o seed cria `WhatsApp_Agent`, `Telegram_Agent` e `Voice_Agent`.

### Telegram

| Aspecto | Detalhe |
|---|---|
| Modos | `polling` (padrão) ou `webhook` (`TELEGRAM_MODE`) |
| Polling | Serviço no profile `telegram-polling` (opt-in) |
| Webhook | `POST /api/v1/channels/webhooks/telegram` |
| Digitando | `sendChatAction(typing)` em loop (~4s) |

### WhatsApp

| Aspecto | Detalhe |
|---|---|
| Provider | Twilio |
| Inbound | `POST /api/v1/channels/webhooks/whatsapp` (form-data) |
| Deduplicação | Chave Redis por `MessageSid` (24h) |
| Digitando | API beta da Twilio (requer `message_sid`) |

O webhook responde com TwiML vazio e o processamento é assíncrono; a resposta sai depois pela API da Twilio. Em desenvolvimento usa-se o Twilio WhatsApp Sandbox (opt-in `join <palavra>`, sessão de 24h).

### Voz

| Aspecto | Detalhe |
|---|---|
| Outbound | Chamada PSTN via Twilio; TwiML servido pelo backend |
| TTS | Tenta Coqui (XTTS-v2, pt) → MP3; fallback `<Say>` Polly pt-BR |
| STT | faster-whisper |

O inbound de voz ao vivo (transcrição bidirecional via Twilio Media Streams) ainda não está conectado (ver Roadmap).

### Indicador "digitando..."

Acionado antes do processamento e encerrado no envio. Telegram: loop a cada ~4s. WhatsApp: disparo único (~25s). Voz: não se aplica. Falhas são logadas, nunca propagadas.

---

## 4. Agentes e orquestração

O comportamento é orquestrado por um grafo (LangGraph), em `agents/orchestrator/graph.py`:
identify_intent → check_escalation → (escalate | generate_response) → send_response → END

| Nó | Função |
|---|---|
| `identify_intent` | Classifica a intenção (saída estruturada do LLM) usando o histórico |
| `check_escalation` | Decide se escala para humano |
| `generate_response` | Gera a resposta com RAG (memória + KB) |
| `send_response` | Envia, persiste (Redis + pgvector) e publica eventos |

O roteamento (`router.py`) é válido para `telegram`, `whatsapp` e `voice`.

### Escalonamento para humano

| Gatilho | Condição |
|---|---|
| Pedido explícito | Intenção "escalar" |
| Baixa confiança | Confiança abaixo de `0,25` |
| Reclamação grave | Reclamação com severidade alta |

Em modo humano (`human_mode:{canal}:{user_id}` no Redis), a IA é silenciada e o operador assume; um sweep (Beat) devolve ao bot após inatividade. Há endpoints para assumir, finalizar e reativar.

### Tabulação

Atendimentos são classificados com códigos de tabulação (padrão call center; seed com 16 códigos). Atribuição por regra ou assistida por IA. A tabulação automática a partir de eventos de chamada Twilio está prevista (ver Roadmap).

### Capacidade e acionamento

- **Janela de horário:** outbound respeita início/fim (fuso SP); receptivo configurável por canal (padrão 24/7).
- **Cadência e slots:** tentativas por hora e conversas simultâneas, com slots no Redis.
- **Capacidade global:** teto ponderado entre canais.
- **Erlang C:** a tela de Capacidade dimensiona atendimentos simultâneos para um nível de serviço (planejamento).

### Identidade institucional

A identidade que o agente assume (nome da empresa, nome de exibição, tom, contexto de negócio, dica de saudação) é configurável e **injetada no prompt** (`agents/identity.py`). É resolvida em duas camadas, com merge campo a campo:

- **Workspace:** identidade padrão do dono da conta (`GET/PUT /api/v1/settings/identity`).
- **Override por agente:** ajustes específicos de um agente (`PATCH /api/v1/agents/{id}/identity`), que prevalecem sobre o workspace quando preenchidos.

A **identidade é separada da base de conhecimento (KB):** a identidade define *quem* o agente é e o autoriza a se apresentar com aquele nome/posicionamento; a KB guarda os *fatos* (preços, prazos, políticas). Sem identidade configurada, o agente se apresenta de forma neutra; sem KB relevante, não inventa fatos.

### Memória e RAG

Memória de curto prazo (Redis) e longo prazo (pgvector). O RAG combina interações passadas semelhantes (isoladas por `user_id`) com a base de conhecimento (upload → chunking → embeddings → pgvector). Sem KB relevante, o agente atua de forma neutra, sem inventar identidade — reforçado no prompt padrão. A ingestão é assíncrona (`worker/tasks/kb_ingestion.py`).

---

## 5. Backend

API em FastAPI (Python 3.12): autenticação, CRUD, webhooks, WebSocket e regras de negócio.

### Estrutura
backend/app/

├── main.py            # App, CORS, lifespan (migrations + seed + bootstrap de settings)

├── api/v1/            # Routers REST + WebSocket

├── core/              # config, database, security, authorization, seed, activation_*, erlang

├── models/            # Modelos SQLAlchemy

├── schemas/           # Schemas Pydantic v2

└── services/          # Regras de negócio (acionamento, capacidade, handoff, KB, settings, voz)

### Routers (`/api/v1`)

| Router | Função |
|---|---|
| `auth` | Cadastro e login (JWT) |
| `agents` | CRUD de agentes + identidade por agente (`PATCH /{id}/identity`) |
| `channels` | CRUD de canais + webhooks (WhatsApp/Telegram/Voz) + status de entrega + áudio outbound |
| `lead_bases` | Bases, import CSV, devolutiva Excel, métricas |
| `leads` | CRUD de leads |
| `campaigns` | CRUD + start/stop + métricas |
| `activation` | Config por canal, liga/desliga, test-dispatch, histórico |
| `metrics` | Métricas de fila |
| `capacity` | Estimativa (hardware + Erlang C) |
| `monitoring` | WebSocket de eventos + histórico |
| `handoff` | Modo humano: listar, assumir, finalizar, reativar |
| `knowledge` | CRUD de documentos KB + upload (`.txt`/`.pdf`/`.docx`) e cadastro manual |
| `settings` | Settings com hot-reload + identidade do workspace (`/settings/identity`) + amostra/teste de voz |
| `tabulacoes` | Catálogo de tabulações |
| `tunnel` | Status do túnel |

### Autenticação e multi-tenant

JWT Bearer. Registros `is_system=true` são visíveis a todos e somente leitura (403 em alteração); os demais são isolados por `user_id` (404 para recursos de terceiros).

### Settings dinâmicas (hot-reload)

Parâmetros de IA, prompts, RAG, voz e handoff são alteráveis em tempo de execução. Ficam em `app_settings` (whitelist `MANAGED_SETTINGS`, categorias `llm`/`stt`/`tts`/`agent`/`system`). Ao salvar, uma versão é incrementada no Redis e um evento de invalidação é publicado; backend e workers recarregam quando detectam a mudança.

---

## 6. Frontend

Dashboard em Next.js 15 + React 19 + TypeScript (Tailwind).

| Tela | Função |
|---|---|
| Visão geral | Contadores (agentes, canais, leads, campanhas) |
| Leads | Bases, importação CSV, CRUD |
| Canais | CRUD WhatsApp/Telegram/Voz e credenciais |
| Agentes | CRUD ACTIVE/RECEPTIVE |
| Campanhas | CRUD (3 canais), iniciar/parar |
| Tabulações | Catálogo de tabulações |
| Acionamento | Motor, teste ad-hoc, histórico |
| Conhecimento | Upload/cadastro KB, ingestão, chunks |
| Monitoramento | Tempo real (WebSocket) + histórico + modo humano |
| Métricas | Funil e fila (gráficos) |
| Capacidade | Estimativa de hardware + Erlang C |
| Configurações | Providers de IA, prompts, RAG, voz, handoff, túnel |

O token JWT fica no `localStorage`; a API é configurável via `NEXT_PUBLIC_API_URL`. O monitoramento usa WebSocket (`/api/v1/monitoring/ws`) alimentado pelo pub/sub do Redis.

---

## 7. Stack tecnológica

**Linguagens:** Python 3.12 (backend/worker/agentes), TypeScript 5.8 (frontend), Node 22 (CI).

**Backend:** FastAPI, Uvicorn, SQLAlchemy 2, Alembic, asyncpg, pgvector, Pydantic 2, Celery, redis, LangGraph, LangChain, twilio, python-telegram-bot, pytest.

**Frontend:** Next.js 15, React 19, Tailwind 3, Recharts, lucide-react, next-themes.

**Modelos de IA (stack OSS, padrão local):**

| Função | Provider | Modelo |
|---|---|---|
| LLM | Ollama | `llama3.1` |
| Embeddings | Ollama | `nomic-embed-text` (768d) |
| STT | faster-whisper | `large-v3` (default; `large-v3-turbo` recomendado) |
| TTS | Coqui | XTTS-v2 (português) |

GPU NVIDIA é recomendada para a stack local (CPU como fallback). **Alternativas de nuvem (opcionais):** OpenAI (`LLM_PROVIDER=openai`, `STT_PROVIDER=openai`, embeddings `text-embedding-3-small` 1536d), ElevenLabs (`TTS_PROVIDER=elevenlabs`) — exigem a respectiva chave de API só quando ativadas.

**Dados:** PostgreSQL 16 + pgvector; Redis 7 (DB0 cache/eventos/handoff/slots, DB1 broker, DB2 results).

---

## 8. Infraestrutura e deploy

### Docker Compose

| Arquivo | Função |
|---|---|
| `docker-compose.yml` | Stack base (+ profile `telegram-polling`) |
| `docker-compose.dev.yml` | Override de desenvolvimento (worker debug, bind mounts) |
| `docker-compose.prod.yml` | Produção (sem bind mounts, múltiplos workers, portas fechadas) |

Portas (host→container): Postgres 25432→5432, Redis 16379→6379, Backend 8000, Frontend 3000, faster-whisper 8001, coqui-tts 8002.

### Túnel Cloudflare

| Modo | Como funciona | Quando usar |
|---|---|---|
| `temporary` | Quick tunnel; URL `*.trycloudflare.com` aleatória, gravada em arquivo | Testes rápidos |
| `named` | Túnel nomeado (token), URL fixa via `PUBLIC_BASE_URL` (domínio próprio) | Uso estável (recomendado) |

No modo `named`, a URL é fixa: o webhook configurado na Twilio não precisa ser reajustado após reinícios.

### Makefile

`make up`, `make down`, `make logs`, `make setup` (sobe + modelos + migrate), `make migrate`, `make pull-models`, `make warm-ollama`, `make shell-backend`, `make test`, `make test-integration`, `make lint`, `make prod-*`, `make opensource-*`. O `telegram-polling` é subido manualmente (profile separado).

### Tarefas agendadas (Celery Beat)

| Tarefa | Intervalo |
|---|---|
| `gerar-devolutivas-diarias` | 00:00 UTC |
| `marcar-nao-atendidos` | a cada hora |
| `limpar-audios-voz` | 03:00 UTC |
| `process-active-activations` | a cada 5 min |
| `process-receptive-queue` | ~30s |
| `sweep-queue-abandonment` | a cada 2 min |
| `sweep-human-handoff-timeouts` | ~60s |

### CI (GitHub Actions)

`backend-tests` (Python 3.12, unit), `backend-integration` (Postgres pgvector + Redis, integração + API), `frontend-build` (Node 22, build do Next.js).

---

## 9. Configuração

Configuração via `.env` (de `.env.example`). No Docker, `DATABASE_URL`/`REDIS_URL` usam `postgres`/`redis`; fora do Compose, `localhost`.

**Grupos:** Aplicação (`DEBUG`, `SECRET_KEY`), PostgreSQL, Redis/Celery, Seleção de provider (`LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`, `EMBEDDING_DIMENSIONS`), Ollama, Whisper, Coqui, Motor de acionamento, Fila receptiva, SLA/abandono, Modo humano/handoff, KB, Capacidade/Erlang, Alternativas de nuvem opcionais (`OPENAI_*`, `ELEVENLABS_*`), Twilio, Túnel (`TUNNEL_MODE`, `CLOUDFLARE_TUNNEL_TOKEN`, `PUBLIC_BASE_URL`), Telegram, Frontend/API.

A **stack OSS local é o padrão** (`LLM_PROVIDER=ollama`, `STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui`, `EMBEDDING_DIMENSIONS=768`) e **não exige nenhuma chave de API**. As chaves de nuvem (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) só são necessárias ao ativar a respectiva alternativa. Canais externos exigem só as credenciais correspondentes (Telegram: `TELEGRAM_BOT_TOKEN`; WhatsApp/Voz: `TWILIO_*`; webhooks: túnel). O `.env` contém segredos e não é versionado.

---

## 10. Testes

Pirâmide com **683 testes**:

| Camada | Marcador | Quantidade |
|---|---|---|
| Unitários | `@pytest.mark.unit` | 288 |
| Integração | `@pytest.mark.integration` | 128 |
| API | `@pytest.mark.api` | 267 |

Execução: `make test` (unit), `make test-integration` (integração), `docker exec autonomous-agent-backend pytest tests/ -v` (completa). O CI roda os três jobs a cada push, com integração aplicando migrations em banco limpo.

---

## 11. Scripts de validação

`backend/scripts/` reúne 21 roteiros de validação ponta a ponta: camadas de acionamento (A–D), receptivo (R-A/R-B/R-C), conduta receptiva (B-1), modo humano (B-2), handoff (H-1/H-2), tabulação (T-2), RAG, KB (1/2), roteamento (fase 4), parada de campanha, test-dispatch, históricos e regressão do worker. Execução: `docker exec autonomous-agent-backend python /workspace/backend/scripts/<script>.py`.

---

## 12. Roadmap e pendências

**Voz:** conectar inbound de voz ao vivo (Twilio Media Streams); abandono real da fila de voz. **Telefonia:** discador SIP próprio; tabulação SIP automática a partir do StatusCallback de chamada Twilio. **Agentes:** workers dedicados de escalonamento e memória (TODO). **Tools:** integrações de CRM e calendário (TODO). **Infra:** módulos Terraform e guias de deploy em nuvem (TODO).

**Concluído recentemente:** remoção do canal de vídeo (consolidação em três canais, stack de avatar removida, enum do banco ajustado); alinhamento do padrão local em todas as camadas (config/compose/.env); aceleração por GPU (NVIDIA) no Compose; rastreamento de entrega WhatsApp (status callback); Telegram via webhook; identidade institucional configurável (workspace + override por agente); URL pública fixa (túnel named); indicador "digitando..."; calibração do escalonamento; agente neutro.

---

## 13. Sobre o projeto (TCC)

Trabalho de Conclusão de Curso intitulado **"Do operador ao Agente: Transformando um atendente de telemarketing em um Agente de IA Autônomo"**, apresentado ao Instituto de Ciências Matemáticas e de Computação (ICMC) da Universidade de São Paulo (USP).

O objetivo acadêmico é demonstrar a viabilidade de substituir fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional e escalar para atendimento humano quando necessário — integrando múltiplos canais de comunicação em uma arquitetura moderna baseada em microsserviços e **modelos de linguagem executados localmente por padrão**, mantendo a flexibilidade de plugar provedores de nuvem sem alterar código.
