# Workers (agentes especializados)

Agentes especializados invocados pelos nós do grafo (`agents/orchestrator/graph.py`). Não confundir com os **workers Celery** (em `worker/`): aqui ficam as unidades de raciocínio do agente de IA.

## Implementados

| Arquivo | Papel |
|---|---|
| `intent_agent.py` | Classifica a intenção da mensagem com **saída estruturada** do LLM (`greeting`, `question`, `complaint`, `purchase`, `cancel`, `escalate`, …) |
| `voice_intent_heuristic.py` | Heurística leve de intenção para o canal de **voz**, evitando uma chamada extra ao LLM (menor latência) |
| `response_agent.py` | Gera a resposta final com o contexto RAG (memória + KB), a identidade institucional e a personalidade do agente |
| `tabulacao_agent.py` | Classifica o desfecho do atendimento (tabulação) para alimentar métricas e CRM |

## Planejados (stubs)

| Arquivo | Status |
|---|---|
| `escalation_agent.py` | 🚧 Stub — a decisão de escalonamento hoje é uma regra pura em `agents/escalation.py` |
| `memory_agent.py` | 🚧 Stub — a memória hoje é gerida diretamente por `agents/memory/` |

Ver [`roadmap.md`](../../docs/roadmap.md) para a evolução dos agentes dedicados.
