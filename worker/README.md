# Worker

Workers **Celery** para processamento assíncrono. O broker e o backend de resultados são o **Redis**. Importa a IA de `agents/` e a config do backend via `PYTHONPATH`.

## Componentes

```
worker/
├── celery_app.py     # instância Celery (broker/result = Redis)
├── tasks/            # tarefas assíncronas (inbound, outbound, sweeps, ingestão…)
├── requirements.txt
└── Dockerfile
```

No Compose há dois serviços baseados nesta imagem:

- **`worker`** — executa as tarefas (inbound, campanhas, ingestão de KB, etc.).
- **`celery-beat`** — agendador periódico (devolutivas, sweeps, scheduler de acionamento, fila receptiva).

## Async dentro de tasks Celery

Tasks Celery são síncronas. Para chamar o grafo (async), usa-se `asyncio.run(...)`. Após cada `asyncio.run` em worker prefork, os clientes async globais são recriados (ver `reset_worker_async_clients` em `agents/orchestrator/graph.py`) para evitar reuso de event loop fechado.

## Regras

- Nunca importar/executar tasks diretamente do `backend/` — sempre via `.delay()` / `.apply_async()`.
- I/O com retry: usar `max_retries` + `countdown`.

Detalhes das tarefas: [`tasks/README.md`](tasks/README.md).
