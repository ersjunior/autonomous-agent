# Unit Tests

> Os testes unitários reais ficam em [`backend/tests/unit/`](../../backend/tests/unit/).

Cobrem lógica pura, sem I/O externo: normalização de contatos/telefone, Erlang C, heurística de intenção em voz, regras de escalonamento, chunking de KB, TwiML de voz, parsing JSON do Ollama, identidade institucional, janelas de acionamento, entre outros.

```bash
make test-unit
```

Visão geral: [`docs/testes.md`](../../docs/testes.md).
