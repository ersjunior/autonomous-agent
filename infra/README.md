# Infrastructure

Infrastructure as Code (IaC) e configurações de deploy.

## Docker (local)

Stack completa em [`docker/`](docker/):

```bash
make up        # desenvolvimento
make prod-up   # produção
```

## Cloud (a implementar)

| Provedor | Caminho |
|----------|---------|
| AWS | `aws/terraform/` + `aws/cloudformation/` |
| Azure | `azure/terraform/` |
| GCP | `gcp/terraform/` |
