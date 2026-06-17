# AWS

> **Status: planejado / não implementado.**

Espaço reservado para a infraestrutura de deploy na **Amazon Web Services**. Ainda não há módulos prontos — os subdiretórios contêm esqueletos:

| Caminho | Conteúdo |
|---|---|
| `terraform/` | Módulos Terraform (planejado) |
| `cloudformation/` | Templates CloudFormation (planejado) |

## Deploy disponível hoje

O modo de execução suportado é **local via Docker Compose** (stack OSS por padrão). Veja [`infra/README.md`](../README.md) e [`infra/docker/README.md`](../docker/README.md).

Quando implementado, o deploy na AWS deverá provisionar equivalentes gerenciados: RDS (PostgreSQL + pgvector), ElastiCache (Redis), execução de containers (ECS/EKS) e os provedores de IA (locais em instância com GPU ou via alternativas de nuvem).
