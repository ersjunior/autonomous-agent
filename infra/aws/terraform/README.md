# AWS Terraform

> **Status: planejado / não implementado.**

Diretório reservado para os módulos Terraform de deploy na AWS. Sem arquivos `.tf` por enquanto.

O deploy suportado hoje é **local via Docker Compose** — veja [`infra/docker/README.md`](../../docker/README.md). Escopo pretendido quando implementado: VPC, RDS (PostgreSQL + pgvector), ElastiCache (Redis), execução de containers (ECS/EKS) e instância com GPU para os provedores de IA locais (ou uso das alternativas de nuvem).
