# Documentação

Documentação técnica do projeto autonomous-agent.

## Início rápido (local)

1. [README principal](../README.md) — instalação, variáveis, comandos `make setup` / `make up`
2. [Deploy local com Docker](deployment/local-docker.md) — passo a passo da stack DEV
3. [infra/docker/README.md](../infra/docker/README.md) — compose, portas, serviços OSS

O modo padrão é a stack **open source** (Ollama + faster-whisper + Coqui), sem chaves pagas de LLM/STT/TTS.

| Pasta | Conteúdo |
|-------|----------|
| [`architecture/`](architecture/) | Visão geral do sistema, design dos agentes, diagramas |
| [`deployment/`](deployment/) | Deploy local (Docker), AWS, Azure, GCP |
| [`api/`](api/) | Referência da API REST |
| [`fine-tuning/`](fine-tuning/) | Fine-tuning de LLM, STT e TTS (comercial e open source) |
