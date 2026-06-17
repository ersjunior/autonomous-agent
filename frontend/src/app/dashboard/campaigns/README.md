# Campaigns

Campanhas outbound — **modo ATIVO** (`/dashboard/campaigns`). Dispara mensagens proativas para uma base de leads, respeitando janela de horário, cadência e capacidade.

## Ciclo de vida

1. Selecionar a base de leads e o canal (WhatsApp/Telegram/Voz).
2. Iniciar: `POST /api/v1/campaigns/{id}/start` enfileira as tarefas.
3. O **scheduler** (Celery Beat) respeita janela (fuso de São Paulo), cadência, slots e capacidade global.
4. Cada mensagem é gerada pelo grafo (personalidade ACTIVE) e entregue pelo canal.

Acompanhe progresso e desfechos (tabulações) pelas telas de métricas e monitoramento. Ver [`docs/canais.md`](../../../../../docs/canais.md) e [`docs/agentes.md`](../../../../../docs/agentes.md).
