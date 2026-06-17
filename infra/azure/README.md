# Azure

> **Status: planejado / não implementado.**

Espaço reservado para a infraestrutura de deploy na **Microsoft Azure**. Ainda não há módulos prontos:

| Caminho | Conteúdo |
|---|---|
| `terraform/` | Módulos Terraform (planejado) |

## Deploy disponível hoje

O modo suportado é **local via Docker Compose**. Veja [`infra/README.md`](../README.md) e [`infra/docker/README.md`](../docker/README.md).

Quando implementado, o deploy no Azure deverá usar equivalentes gerenciados: Azure Database for PostgreSQL (pgvector), Azure Cache for Redis, execução de containers (Container Apps/AKS) e provedores de IA (locais com GPU ou alternativas de nuvem).
