# Azure Terraform

> **Status: planejado / não implementado.**

Diretório reservado para os módulos Terraform de deploy na Azure. Sem arquivos `.tf` por enquanto.

O deploy suportado hoje é **local via Docker Compose** — veja [`infra/docker/README.md`](../../docker/README.md). Escopo pretendido: rede, Azure Database for PostgreSQL (pgvector), Azure Cache for Redis, execução de containers (Container Apps/AKS) e GPU para os provedores de IA locais (ou alternativas de nuvem).
