# Documentação

Documentação técnica do projeto autonomous-agent.

## Início rápido (local)

1. [README principal](../README.md) — instalação, variáveis, comandos `make setup` / `make up`
2. [Deploy local com Docker](deployment/local-docker.md) — passo a passo da stack DEV
3. [infra/docker/README.md](../infra/docker/README.md) — compose, portas, serviços OSS

O sistema é **agnóstico de provedor** e roda a **stack OSS local por padrão** (Ollama + faster-whisper + Coqui + `nomic-embed-text`), **sem chaves de API**. Cada camada pode ser plugada a uma **alternativa de nuvem (opcional)** por variável de ambiente, sem alterar código.

## Documentação principal

| Arquivo | Conteúdo |
|---------|----------|
| [documentacao.md](documentacao.md) | Visão consolidada do sistema |
| [arquitetura.md](arquitetura.md) | Arquitetura, fluxos e memória |
| [stack.md](stack.md) | Stack tecnológica e versões |
| [backend.md](backend.md) | API FastAPI, auth, settings |
| [frontend.md](frontend.md) | Dashboard Next.js |
| [canais.md](canais.md) | Telegram, WhatsApp e Voz |
| [agentes.md](agentes.md) | LangGraph, RAG, handoff, capacidade |
| [infra.md](infra.md) | Docker, Makefile, CI, Celery Beat |
| [configuracao.md](configuracao.md) | Variáveis de ambiente |
| [scripts.md](scripts.md) | Scripts `validate_*` |
| [testes.md](testes.md) | Pirâmide de testes (797 testes) |
| [roadmap.md](roadmap.md) | Pendências e trabalho futuro |

## Apresentação e demo

| Arquivo | Conteúdo |
|---------|----------|
| [CHECKLIST_DEMO.md](CHECKLIST_DEMO.md) | Checklist pré-demo ao vivo |
| [ROTEIRO_APRESENTACAO.md](ROTEIRO_APRESENTACAO.md) | Roteiro de apresentação (TCC) |
| [SMOKE_TEST.md](SMOKE_TEST.md) | Smoke test pré-apresentação |

## Pastas complementares

| Pasta | Conteúdo |
|-------|----------|
| [`architecture/`](architecture/) | Visão geral do sistema, design dos agentes, diagramas (parcialmente planejado) |
| [`deployment/`](deployment/) | Deploy local (Docker) implementado; AWS/Azure/GCP planejados |
| [`api/`](api/) | Referência da API REST (use `/docs` Swagger; doc dedicada planejada) |
| [`fine-tuning/`](fine-tuning/) | Fine-tuning de LLM, STT e TTS (stack OSS e alternativas de nuvem) |
| [`kb-templates/`](kb-templates/) | Modelos para estruturar a base de conhecimento (KB) |
