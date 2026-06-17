# Tests

> A suíte de testes **automatizada vive em [`backend/tests/`](../backend/tests/)** (pytest). Esta pasta `tests/` na raiz guarda apenas notas/placeholders por categoria.

## Onde estão os testes

```
backend/tests/
├── unit/          # testes unitários (lógica pura, sem I/O externo)
├── integration/   # testes de integração (banco, pgvector, sweeps)
├── api/           # testes de API (FastAPI TestClient + auth)
└── conftest.py    # fixtures compartilhadas
```

## Como rodar

```bash
make test                 # suíte completa
make test-unit            # apenas unit
make test-integration     # apenas integração
make test-api             # apenas API
```

## Contagem (via `pytest --collect-only`)

| Categoria | Testes |
|---|---|
| Unitários | 288 |
| Integração | 128 |
| API | 267 |
| **Total** | **683** |

Detalhes da estratégia de testes: [`docs/testes.md`](../docs/testes.md).
