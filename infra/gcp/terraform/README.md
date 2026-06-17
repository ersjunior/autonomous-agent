# GCP Terraform

> **Status: planejado / não implementado.**

Diretório reservado para os módulos Terraform de deploy no GCP. Sem arquivos `.tf` por enquanto.

O deploy suportado hoje é **local via Docker Compose** — veja [`infra/docker/README.md`](../../docker/README.md). Escopo pretendido: rede (VPC), Cloud SQL for PostgreSQL (pgvector), Memorystore (Redis), execução de containers (Cloud Run/GKE) e GPU para os provedores de IA locais (ou alternativas de nuvem).
