# Integration Tests

> Os testes de integração reais ficam em [`backend/tests/integration/`](../../backend/tests/integration/).

Exercitam componentes com dependências reais (PostgreSQL/pgvector, Redis, pools): recuperação RAG da KB, memória de longo prazo, pool pgvector, sweeps de inatividade e fila, histórico de acionamento/atendimento, handoff humano, métricas por agente, ownership de seeds, etc.

```bash
make test-integration
```

Visão geral: [`docs/testes.md`](../../docs/testes.md).
