# Testes

O projeto adota uma pirâmide de testes automatizados (pytest), complementada pelos scripts de validação manual (veja [scripts.md](scripts.md)).

## Pirâmide

| Camada | Marcador | Quantidade | Foco |
|---|---|---|---|
| Unitários | `@pytest.mark.unit` | 136 | Funções e regras isoladas, sem dependências externas |
| Integração | `@pytest.mark.integration` | 104 | Componentes com banco real (Postgres + pgvector) e Redis |
| API | `@pytest.mark.api` | 213 | Endpoints HTTP de ponta a ponta |
| **Total** | | **453** | |

A configuração dos marcadores está em `backend/pyproject.toml` (com `asyncio_mode = auto`).

## Como rodar

```bash
# Unitários (rápidos, sem dependências externas)
make test

# Integração (sobe/usa o Postgres de teste do Compose)
make test-integration

# Suíte completa dentro do container
docker exec autonomous-agent-backend pytest tests/ -v
```

Os testes de integração e de API precisam de um banco de teste acessível. Ao rodar dentro do Compose, use o hostname interno do Postgres (`postgres`), não `localhost` — o alvo `make test-integration` já cuida disso.

## Integração contínua (CI)

A cada push, o GitHub Actions (`.github/workflows/ci.yml`) executa três jobs:

| Job | Ambiente | O que valida |
|---|---|---|
| `backend-tests` | Python 3.12 | Testes unitários |
| `backend-integration` | Postgres (pgvector) + Redis | Testes de integração e de API (banco do zero, migrations aplicadas) |
| `frontend-build` | Node 22 | Build de produção do Next.js |

O job de integração roda as migrations em um banco limpo, o que também valida que a cadeia de migrations (incluindo a remoção do canal de vídeo) está consistente.

## Observações

- A suíte completa cobre os fluxos de acionamento, fila receptiva, handoff, RAG, KB, tabulação e os três canais.
- Para validação manual e exploratória de cada camada em um ambiente de pé, use os scripts em `backend/scripts/` ([scripts.md](scripts.md)).
