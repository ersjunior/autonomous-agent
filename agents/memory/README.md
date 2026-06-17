# Memory

Memória conversacional em dois níveis, isolada por contato (`user_id`).

## Arquivos

| Arquivo | Papel |
|---|---|
| `short_term.py` | Histórico imediato da conversa no **Redis** (`chat:{user_id}`, TTL ~1h) |
| `long_term.py` | Memória semântica no **PostgreSQL + pgvector** (`interactions.embedding`) |
| `pgvector_pool.py` | Pool `asyncpg` reaproveitável para buscas vetoriais (compartilhado com a KB) |

## Curto prazo (Redis)

Mantém as últimas trocas da conversa para dar contexto imediato ao LLM. Expira por TTL, então não cresce indefinidamente. Lido em `identify_intent` e atualizado em `send_response`.

## Longo prazo (pgvector)

Cada interação é embeddada e gravada em `interactions`. Em conversas futuras, `retrieve_similar_memories` faz busca por similaridade de cosseno **isolada por `user_id`**, recuperando trocas passadas relevantes para enriquecer a resposta (parte 1 do RAG).

A dimensão do vetor acompanha o provedor de embeddings (`768` Ollama `nomic-embed-text` por padrão, `1536` OpenAI), controlada por `EMBEDDING_DIMENSIONS` e aplicada via migration Alembic.

## RAG em dois níveis

A memória de longo prazo (este módulo) é combinada, em paralelo, com a **base de conhecimento institucional** (`agents/tools/knowledge_base.py`) durante a geração da resposta. Ver [`docs/arquitetura.md`](../../docs/arquitetura.md).
