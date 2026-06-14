# Autonomous Agent

[![Licença: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-blue.svg)](LICENSE)

Sistema multi-agente de inteligência artificial para atendimento autônomo de clientes em múltiplos canais — **Telegram, WhatsApp e Voz**. O agente opera em modo **ativo** (campanhas outbound para leads) ou **receptivo** (resposta a mensagens recebidas), com orquestração por grafo (LangGraph) e **IA rodando localmente por padrão** (sem depender de provedores de nuvem).

## O que é

Uma plataforma que substitui fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional (memória de curto e longo prazo), consultar uma base de conhecimento (RAG) e escalar para atendimento humano quando necessário — integrando múltiplos canais em uma arquitetura de microsserviços.

## Como funciona

Uma mensagem entra por um canal (webhook ou polling), é processada de forma assíncrona por um worker que invoca o grafo de agentes, e a resposta é gerada com apoio de RAG (memória do contato + base de conhecimento) antes de retornar pelo mesmo canal.
Canal → Backend (FastAPI) → Fila (Redis/Celery) → Worker → Grafo (LangGraph + RAG) → Resposta

A IA roda **localmente** por padrão: LLM e embeddings via **Ollama** (`llama3.1` + `nomic-embed-text`), STT via **faster-whisper** e TTS via **Coqui** (XTTS-v2, português). Provedores comerciais (OpenAI, ElevenLabs) são suportados como alternativa configurável.

## Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy, Celery, LangGraph
- **Frontend:** Next.js 15, React 19, TypeScript, Tailwind
- **Dados:** PostgreSQL 16 + pgvector, Redis 7
- **IA local:** Ollama, faster-whisper, Coqui (alternativas: OpenAI, ElevenLabs)
- **Infra:** Docker Compose, Cloudflare Tunnel, Twilio, GitHub Actions

## Funcionalidades

- **Três canais:** Telegram, WhatsApp e Voz, com indicador de "digitando..."
- **Dois perfis de agente:** ativo (campanhas) e receptivo (inbound com fila e capacidade)
- **RAG em dois níveis:** memória semântica por contato + base de conhecimento institucional
- **Escalonamento para humano:** por intenção, baixa confiança ou reclamação grave
- **Tabulação** de atendimentos (padrão call center)
- **Dimensionamento de capacidade** com Erlang C
- **Configuração dinâmica** (hot-reload) de providers de IA, prompts e parâmetros
- **Dashboard** completo de gestão e monitoramento em tempo real

## Como rodar

Pré-requisitos: Docker + Docker Compose. (Opcional para dev local: Python 3.12, Node 22.)

```bash
# 1. Clonar
git clone https://github.com/ersjunior/autonomous-agent.git
cd autonomous-agent

# 2. Configurar ambiente
cp .env.example .env   # ajuste as credenciais dos canais que for usar

# 3. Subir tudo (containers + modelos de IA + migrations)
make setup

# 4. (Opcional) Telegram em modo polling
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml --profile telegram-polling up -d telegram-polling
```

Acesse o dashboard em <http://localhost:3000> e a API em <http://localhost:8000/docs>.

## Documentação

A documentação completa está em [`docs/`](docs/). Comece pelo documento consolidado ou navegue por parte:

| Documento | Conteúdo |
|---|---|
| [docs/documentacao.md](docs/documentacao.md) | **Documentação consolidada** (tudo em um, com sumário) |
| [docs/arquitetura.md](docs/arquitetura.md) | Visão geral, serviços, fluxos e pipeline de IA |
| [docs/stack.md](docs/stack.md) | Linguagens, bibliotecas e modelos de IA |
| [docs/backend.md](docs/backend.md) | API, routers, autenticação e settings dinâmicas |
| [docs/frontend.md](docs/frontend.md) | Dashboard e suas telas |
| [docs/canais.md](docs/canais.md) | Telegram, WhatsApp e Voz |
| [docs/agentes.md](docs/agentes.md) | Grafo, escalonamento, capacidade, memória e RAG |
| [docs/infra.md](docs/infra.md) | Docker, túnel Cloudflare, Makefile e CI |
| [docs/configuracao.md](docs/configuracao.md) | Variáveis de ambiente (`.env`) |
| [docs/scripts.md](docs/scripts.md) | Scripts de validação |
| [docs/testes.md](docs/testes.md) | Pirâmide de testes e CI |
| [docs/roadmap.md](docs/roadmap.md) | Pendências e trabalhos futuros |
| [docs/CHECKLIST_DEMO.md](docs/CHECKLIST_DEMO.md) | Checklist pré-demonstração |

## Licença

Distribuído sob a licença [MIT](LICENSE).

---

## Sobre o projeto (TCC)

Este projeto foi desenvolvido como Trabalho de Conclusão de Curso (TCC) intitulado **"Do operador ao Agente: Transformando um atendente de telemarketing em um Agente de IA Autônomo"**, apresentado ao Instituto de Ciências Matemáticas e de Computação (ICMC) da Universidade de São Paulo (USP).

O objetivo acadêmico é demonstrar a viabilidade de substituir fluxos tradicionais de telemarketing por um agente autônomo capaz de identificar intenções, manter contexto conversacional e escalar para atendimento humano quando necessário — integrando múltiplos canais de comunicação em uma arquitetura moderna baseada em microsserviços e modelos de linguagem executados localmente.
