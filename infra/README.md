# Infrastructure

Infrastructure as Code (IaC) e configurações de deploy.

## Docker (local)

Stack completa em [`docker/`](docker/). O modo padrão inclui **Ollama + faster-whisper + Coqui**
(sem profile, sem chaves pagas de LLM/STT/TTS).

```bash
cp .env.example .env   # primeira vez
make setup             # 1ª subida: up + modelos Ollama + migrations
make up                # desenvolvimento (subidas seguintes)
make down
make prod-up           # produção (override prod)
```

Documentação detalhada: [`docker/README.md`](docker/README.md).

## Cloud (a implementar)

| Provedor | Caminho |
|----------|---------|
| AWS | `aws/terraform/` + `aws/cloudformation/` |
| Azure | `azure/terraform/` |
| GCP | `gcp/terraform/` |
