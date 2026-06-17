# Tasks

Tarefas Celery do projeto. Cobrem o modo **ATIVO** (outbound), o **RECEPTIVO** (inbound) e rotinas periódicas (sweeps/scheduler) executadas pelo `celery-beat`.

## Inbound / conversa (RECEPTIVO)

| Tarefa | Papel |
|---|---|
| `inbound_handler.py` | Processa mensagem recebida: resolve lead/agente, checa modo humano e invoca o grafo |
| `conversation_routing.py` | Roteamento/encaminhamento de conversas |
| `voice_inbound_turn.py` | Processa um turno de chamada de voz recebida |
| `receptive_queue.py` | Avança a fila receptiva conforme a capacidade |

## Outbound (ATIVO)

| Tarefa | Papel |
|---|---|
| `outbound_campaign.py` | Envia mensagem ativa de campanha para um lead (via grafo + canal) |
| `activation_scheduler.py` | Agenda disparos respeitando janela, cadência, slots e capacidade |

## Rotinas periódicas (celery-beat)

| Tarefa | Papel |
|---|---|
| `inactivity_sweep.py` | Detecta inatividade e dispara follow-ups/encerramentos |
| `human_handoff_sweep.py` | Expira/limpa estados de modo humano |
| `status_sweep.py` | Reconciliação de status de entrega |
| `queue_abandon_sweep.py` | Trata abandono na fila receptiva |
| `devolutiva_task.py` | Gera devolutivas/tabulações de fechamento |
| `lead_tracking.py` | Atualiza rastreamento/estado dos leads |
| `voice_cleanup.py` | Limpeza de artefatos de chamadas de voz |

## Ingestão

| Tarefa | Papel |
|---|---|
| `kb_ingestion.py` | Ingestão assíncrona de documentos da base de conhecimento (extração → chunking → embeddings → pgvector) |

Padrões de implementação: [`worker/README.md`](../README.md).
