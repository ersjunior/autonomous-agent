# GCP

> **Status: planejado / não implementado.**

Espaço reservado para a infraestrutura de deploy no **Google Cloud Platform**. Ainda não há módulos prontos:

| Caminho | Conteúdo |
|---|---|
| `terraform/` | Módulos Terraform (planejado) |

## Deploy disponível hoje

O modo suportado é **local via Docker Compose**. Veja [`infra/README.md`](../README.md) e [`infra/docker/README.md`](../docker/README.md).

Quando implementado, o deploy no GCP deverá usar equivalentes gerenciados: Cloud SQL for PostgreSQL (pgvector), Memorystore (Redis), execução de containers (Cloud Run/GKE) e provedores de IA (locais com GPU ou alternativas de nuvem).
