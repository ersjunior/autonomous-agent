# GitHub Workflows

Pipelines de CI/CD do projeto autonomous-agent.

| Workflow | Gatilho | Secrets |
|----------|---------|---------|
| `ci.yml` | Push/PR em `main` e `develop` | Nenhum |
| `docker-publish.yml` | Tag `v*` | `DOCKER_USERNAME` e `DOCKER_TOKEN` (opcionais) |

Sem secrets Docker Hub configurados, `docker-publish.yml` exibe aviso informativo e conclui com sucesso — o deploy local via Docker Compose não é afetado.
