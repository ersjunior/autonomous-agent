# Tools

Ferramentas que estendem o conhecimento e as ações dos agentes.

## Implementado

| Arquivo | Papel |
|---|---|
| `knowledge_base.py` | **Recuperação RAG da base de conhecimento institucional** (`KnowledgeBaseRetriever`). Busca semântica em `kb_chunks` (join com `kb_documents`), filtrando por documentos `READY` e por escopo: chunks institucionais (`is_system=True`, visíveis a todos) + chunks do dono do agente/campanha. Degrada graciosamente (retorna `[]`) se a busca/embed falhar. |
| `calendar_tool.py` | **Agenda interna (Postgres)** — fachada assíncrona sobre `appointment_service`: `list_available_slots` e `create_appointment` na tabela `appointments`. |

A busca da KB roda **em paralelo** com a memória de longo prazo durante a geração da resposta (RAG em dois níveis — ver [`docs/arquitetura.md`](../../docs/arquitetura.md)).

## Planejados (stubs)

| Arquivo | Status |
|---|---|
| `crm_tool.py` | 🚧 Stub — integração com CRM (consulta/gravação de dados do cliente) |

Ver [`roadmap.md`](../../docs/roadmap.md).
