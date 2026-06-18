# Orchestrator

Orquestração da conversa com **LangGraph**. Define o grafo de agentes, o roteamento de entrada e o estado compartilhado entre os nós.

## Arquivos

| Arquivo | Papel |
|---|---|
| `graph.py` | Monta e compila o grafo (`agent_graph`) com os nós e as arestas condicionais |
| `router.py` | Roteamento de entrada por canal (`route_message`) e decisão pós-escalonamento |
| `state.py` | `AgentState` — o dicionário tipado que trafega entre os nós |
| `booking_handler.py` | Fluxo conversacional de agendamento (`process_booking_turn`); estado Redis |
| `farewell_handler.py` | Encerramento autônomo de ligação de voz (`process_farewell_turn`) |

## Grafo

```mermaid
flowchart TD
    START([START]) --> identify_intent
    identify_intent --> check_escalation
    check_escalation -->|escala| escalate
    check_escalation -->|nao escala| handle_booking
    handle_booking --> handle_farewell
    handle_farewell --> generate_response
    escalate --> send_response
    generate_response --> send_response
    send_response --> END_NODE([END])
```

| Nó | Função |
|---|---|
| `identify_intent` | Classifica a intenção (saída estruturada do LLM; heurística leve em voz, incl. `schedule`/`farewell`), usando o histórico do Redis |
| `check_escalation` | Decide escalonamento via `agents/escalation.py` (`resolve_should_escalate`) |
| `handle_booking` | Avança agendamento conversacional; prepara `booking_context` ou resposta pré-montada na voz |
| `handle_farewell` | Encerramento de voz (`should_hangup`); roda após booking |
| `escalate` | Monta a resposta de encaminhamento para humano |
| `generate_response` | Gera a resposta com **RAG em dois níveis** (memória + KB), em paralelo; injeta `booking_context` |
| `send_response` | Persiste no Redis (curto prazo) e no pgvector (longo prazo) e publica eventos de monitoramento |

A aresta condicional após `check_escalation` é resolvida por `route_after_escalation_check` (`router.py`).

## Roteamento de entrada

`route_message` valida o canal (`telegram`, `whatsapp`, `voice`) antes de processar. Canais desconhecidos são rejeitados.

Visão completa do comportamento: [`docs/agentes.md`](../../docs/agentes.md) e [`docs/documentacao.md`](../../docs/documentacao.md) §9.
