# Suíte de testes

Referência da infraestrutura e dos **443 testes** do backend (`backend/tests/`). Contagens confirmadas com `pytest --collect-only` (jun/2026):

| Camada | Pasta | Testes |
|--------|-------|--------|
| Unitários | `tests/unit/` | **128** |
| Integração | `tests/integration/` | **103** |
| API | `tests/api/` | **212** |
| **Total** | | **443** |

---

## Visão geral — pirâmide em 3 camadas

```
        ┌─────────────┐
        │  Unitários  │  128 — lógica pura, ms, sem rede/DB
        ├─────────────┤
        │ Integração  │  103 — serviços + SQL + pgvector + Redis
        ├─────────────┤
        │     API     │  212 — contratos HTTP end-to-end in-process
        └─────────────┘
```

**Por que três camadas?**

1. **Unitários** — feedback instantâneo em fórmulas, mapeamentos e parsers; falhas apontam a linha exata sem flaky de infra.
2. **Integração** — prova comportamento real de ORM, transações, vetores e filas; pega bugs de SQL, constraints e isolamento de tenant que mocks escondem.
3. **API** — valida status codes, schemas de resposta, auth e regras de autorização expostas ao dashboard; regressões de contrato quebram o frontend cedo.

Cada camada tem marker pytest (`unit`, `integration`, `api`) para filtragem seletiva.

---

## Camada 1 — Testes unitários (`tests/unit/`)

**O que são:** funções e classes testadas **sem** PostgreSQL, Redis ou rede. Dependências externas (HTTP, psutil, arquivos) são controladas com `tmp_path`, `monkeypatch` ou valores fixos.

**Config:** `asyncio_mode = auto` no `pyproject.toml`; marker `@pytest.mark.unit`.

### Arquivos e cobertura

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `test_erlang.py` | 21 | Erlang B/C, nível de serviço, `required_agents`, intensidade de tráfego |
| `test_activation_window.py` | 17 | Janela `horario_inicio`–`horario_fim`, virada de meia-noite, parse `HH:MM` |
| `test_tabulacao_mapping.py` | 22 | Regras intent/status → código, normalização SIP, mapeamento inverso status |
| `test_contact_normalization.py` | 11 | `canonical_contact_ids`, inferência de canal (WhatsApp/voz/Telegram) |
| `test_phone.py` | 9 | Dígitos, E.164, prefixo Brasil |
| `test_kb_chunking.py` | 8 | Divisão de texto em chunks, overlap, limites mín/máx |
| `test_capacity_estimate.py` | 7 | Orçamento CPU/RAM, boost GPU, custos por canal |
| `test_resolve_should_escalate.py` | 8 | Escalonamento: intent `escalate`, confiança, gravidade de reclamação |
| `test_telegram_config.py` | 7 | URL de webhook, modo polling vs webhook |
| `test_tunnel_config.py` | 6 | Resolução de URL pública (env vs arquivo tunnel) |
| `test_tunnel_status.py` | 11 | Status do túnel, probe de health, divergência env/arquivo |

### Âncora Erlang (R-C)

Caso de referência compartilhado com `validate_layer_rc_capacity.py`:

- **A** = 10 Erlangs, **N** = 14 agentes, **AHT** = 180 s, **T** = 20 s  
- **SL esperado** ≈ **0,8725** (tolerância ±0,002)

```python
# test_erlang.py — prova contra valor analítico, não contra mock
sl = erlang.service_level(REF_N, REF_A, REF_T, REF_AHT)
assert sl == pytest.approx(0.8725, abs=0.002)
```

---

## Camada 2 — Testes de integração (`tests/integration/`)

**O que são:** serviços e repositórios contra **PostgreSQL 16 + pgvector** e **Redis 7** reais. Schema aplicado via **Alembic** (`alembic upgrade head`), não `create_all`.

**Marker:** `@pytest.mark.integration`.

### Infraestrutura compartilhada (`tests/db_fixtures.py`)

| Fixture | Papel |
|---------|--------|
| `test_engine` (sessão) | Cria banco `*_test` se não existir, extensão `vector`, roda migrations |
| `db_session` | **Transação externa + rollback** no teardown — nada persiste entre testes |
| | `join_transaction_mode="create_savepoint"` — `commit()` interno vira savepoint |
| `pgvector_conn` | Extrai `asyncpg.Connection` **da mesma transação** que `db_session`; RAG/KB usam SQL vetorial real com rollback |
| `clean_redis` | Flush de chaves de handoff, capacidade, slots e fila — **“rollback do Redis”** |
| `owner_ctx` | Usuário + campanha + base + lead (via `create_owner_context`) |
| `second_owner` | Segundo tenant para testes de isolamento |
| `seeded_catalog` / `system_seeds` | Admin, tabulações e seeds completos |
| `mock_classify` | Substitui LLM de tabulação por retorno configurável |
| `mock_capacity_release` | Evita side effects Redis em transições terminais de LI |

**Proteções de banco:**

- `TEST_DATABASE_URL` deve terminar em `_test` (ex.: `autonomous_agent_test`)
- Se `DATABASE_URL` apontar para o mesmo banco que não seja `*_test`, a suíte aborta

### Arquivos e cobertura

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `test_seed_smoke.py` | 3 | Idempotência de seed, visibilidade dentro da transação, rollback limpa dados |
| `test_seeds_ownership.py` | 12 | Seeds de canais/agentes/tabulações, `is_system`, IMPORT read-only, visibilidade |
| `test_tabulacao_assignment.py` | 14 | Regras, SIP, escalonamento, IA mockada, catálogo por dono |
| `test_lead_tracking.py` | 17 | Upsert LI, acionamento, busca por telefone/Telegram, tabulação inbound, release de capacidade |
| `test_queue_entry.py` | 10 | Fila WAITING/ANSWERED/ABANDONED, idempotência, métricas, sweep só voz |
| `test_activation_history.py` | 10 | Paginação, filtros, ownership, finalizar manual com tabulação |
| `test_attendance_history.py` | 10 | Histórico híbrido, órfãos receptivos, merge WhatsApp, stats de conversa |
| `test_kb_retrieval.py` | 6 | RAG da base de conhecimento: similaridade, escopo, status READY, threshold |
| `test_long_term_memory.py` | 6 | Memória semântica do grafo: ordenação, isolamento por `user_id`, threshold |
| `test_human_handoff_db.py` | 4 | Finalizar handoff no DB, assume, sweeps de timeout (fila e assumido) |
| `test_capacity_activation_settings.py` | 9 | λ/AHT observados, análise de capacidade, merge de settings, hot-reload Redis |

### Destaques

**Isolamento de tenant** — `test_seeds_ownership`, `test_activation_history` (`ownership_isolates_tenants`), `test_attendance_history` (`orphan_not_visible_to_other_tenant`) garantem que registros de um `user_id` não vazam para outro.

**RAG com vetores ortogonais** — helpers `unit_vector(n)` geram embeddings perpendiculares; consulta com `e0` retorna chunk `e0` primeiro e chunks ortogonais ficam abaixo do threshold configurado (`test_kb_retrieval`, `test_long_term_memory`).

---

## Camada 3 — Testes de API (`tests/api/`)

**O que são:** rotas FastAPI via **`httpx.AsyncClient`** + **`ASGITransport`** (in-process, sem TCP).

**Fixtures** (`tests/api/conftest.py`):

| Fixture | Papel |
|---------|--------|
| `test_app` | Substitui `get_db` pela `db_session` transacional; lifespan noop (sem seed/migrate duplicado) |
| `client` | Cliente HTTP anônimo |
| `auth_client` | Override de `get_current_user` → `owner_ctx.user` |
| `other_auth_client` | Segundo tenant autenticado |
| `auth_headers` | JWT real (`create_access_token`) — exercita decode + lookup no DB |

**Marker:** `@pytest.mark.api`.

### Arquivos e cobertura

| Arquivo | Cobertura principal |
|---------|---------------------|
| `test_health_api.py` | `GET /health` sem auth |
| `test_auth_api.py` | Register, login, JWT, endpoints protegidos |
| `test_smoke_authenticated.py` | Smoke: listagem de agentes autenticado |
| `test_agents_api.py` | CRUD agentes, `is_system`, isolamento |
| `test_channels_api.py` | CRUD canais |
| `test_campaigns_api.py` | CRUD campanhas, agente RECEPTIVE permitido na criação |
| `test_campaign_lifecycle_api.py` | Start / stop / retomar, filas Celery mockadas |
| `test_leads_api.py` | CRUD leads, base IMPORT read-only |
| `test_lead_bases_api.py` | Bases, import CSV, devolutiva Excel, métricas |
| `test_tabulacoes_api.py` | Catálogo call center + customizados |
| `test_activation_api.py` | Settings por canal, start/stop, histórico, finalizar, test-dispatch |
| `test_monitoring_api.py` | Histórico de atendimentos, threads, órfãos, paginação |
| `test_handoff_api.py` | Modo humano: active, assume, finalize, reactivate, **isolamento por tenant** |
| `test_knowledge_api.py` | Upload/manual KB, ownership, delete system |
| `test_aggregates_api.py` | Capacidade, fila, tunnel, settings (GET/PUT) |

**Total:** 212 testes (inclui casos parametrizados de payload inválido, dias de métrica, etc.).

---

## Configuração pytest (`backend/pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = [
    "-v", "--tb=short",
    "--cov=app", "--cov=agents.channels.phone",
    "--cov-report=term-missing:skip-covered",
]
markers = [
    "unit: testes unitários puros (sem banco, Redis ou rede)",
    "integration: testes de integração com Postgres real (pgvector + Alembic)",
    "api: testes de contrato HTTP via AsyncClient (Camada 3)",
]
```

**Coverage:** `app/` e `agents.channels.phone`; omite `tests/`, `alembic/`, `scripts/`.

---

## Como rodar

### Pré-requisitos (integração + API)

Stack Docker com Postgres e Redis (`make up`). Variáveis típicas:

```env
TEST_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test
REDIS_URL=redis://redis:6379/0
```

No host Windows/Linux fora do compose, use `@localhost:5432` em vez de `@postgres:5432`.

### Comandos essenciais

```bash
# Via Makefile (dentro do compose)
make test                    # unitários — 128 testes, ~segundos
make test-integration        # integração — 103 testes

# Suíte completa (unit + integration + api)
docker exec autonomous-agent-backend pytest tests/ -v --tb=short

# Por camada / marker
docker exec autonomous-agent-backend pytest tests/unit -m unit -v
docker exec -e TEST_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test \
  -e DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test \
  autonomous-agent-backend pytest tests/integration -m integration -v
docker exec -e TEST_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test \
  -e DATABASE_URL=postgresql://postgres:postgres@postgres:5432/autonomous_agent_test \
  autonomous-agent-backend pytest tests/api -m api -v

# Arquivo ou teste isolado
docker exec autonomous-agent-backend pytest tests/unit/test_erlang.py -v
docker exec autonomous-agent-backend pytest tests/api/test_handoff_api.py::test_handoff_assume_foreign_owner_returns_404 -v

# Collect-only (validar contagem)
docker exec autonomous-agent-backend pytest tests/unit --collect-only -q
docker exec autonomous-agent-backend pytest tests/integration --collect-only -q
docker exec autonomous-agent-backend pytest tests/api --collect-only -q
```

**Nota:** Camadas 2 e 3 compartilham `tests/db_fixtures.py`; testes de API **dependem** do mesmo Postgres migrado que a integração.

---

## CI (`.github/workflows/ci.yml`)

| Job | Quando | O que roda |
|-----|--------|------------|
| **backend-tests** | push/PR em `main` e `develop` | `pytest tests/unit` — sem services |
| **backend-integration** | idem | Services: `pgvector/pgvector:pg16`, `redis:7-alpine`; `pytest tests/integration tests/api` com `TEST_DATABASE_URL`, `REDIS_URL`, `CELERY_*` |
| **frontend-build** | idem | `npm ci` + `npm run build` em `frontend/` |

`PYTHONPATH` no CI: `{workspace}:{workspace}/backend:{workspace}/worker` (igual ao container).

---

## Bugs encontrados pelos testes

Exemplos de regressões reais capturadas pela Camada 3 — úteis para demonstrar valor da suíte no TCC.

### 1. Shadowing de `status` em `/activation/history`

**Sintoma:** query params `skip=-1` ou `limit` inválido retornavam **500** (`AttributeError`) em vez de **400**.

**Causa:** parâmetro de query nomeado `status` sombreava o import `from fastapi import status`. Em validações como `status.HTTP_400_BAD_REQUEST`, Python acessava a string do filtro, não o módulo de constantes HTTP.

**Correção:** renomear para `status_filter: str | None = Query(None, alias="status")` em `app/api/v1/activation.py`.

**Como o teste pegou:** `test_activation_history_invalid_skip_returns_400` e `test_activation_history_invalid_limit_returns_400` em `test_activation_api.py` — assert `response.status_code == 400`.

### 2. Mesmo shadowing em `/monitoring/attendance-history`

**Sintoma e causa:** idênticos ao item 1, no router de monitoramento.

**Correção:** `status_filter` + `alias="status"` em `app/api/v1/monitoring.py`.

**Como o teste pegou:** `test_attendance_history_invalid_skip_returns_400` e `test_attendance_history_invalid_limit_returns_400` em `test_monitoring_api.py`.

### 3. Isolamento de tenant ausente no handoff

**Sintoma:** qualquer usuário autenticado podia listar, assumir, finalizar ou reativar handoffs de **outro tenant** — falha grave de autorização multi-usuário.

**Causa:** estado Redis `human_mode:{channel}:{user_id}` não carregava o dono da conversa; endpoints não filtravam por `owner_user_id`.

**Correção:** propagar `owner_user_id` em `enter_human_mode()` / payload Redis e validar ownership em `human_handoff.py` e rotas `/api/v1/handoff/*`.

**Como o teste pegou:** suite `test_handoff_api.py` — `test_handoff_active_filters_by_tenant_owner_sees_only_own`, `test_handoff_assume_foreign_owner_returns_404`, `test_handoff_finalize_foreign_owner_returns_404`, `test_handoff_reactivate_foreign_owner_returns_404`.

---

## Decisões de design

| Decisão | Motivo |
|---------|--------|
| **Postgres real, não SQLite** | pgvector, JSONB, enums PostgreSQL e semântica de transação async diferem de SQLite; falsos positivos/negativos seriam frequentes. |
| **Rollback transacional por teste** | Velocidade (~100+ testes/min) sem `truncate`/`drop`; cada teste parte de schema migrado limpo logicamente. |
| **Redis real, chaves limpas** | Lua scripts, TTL e ZSET de fila/slots não reproduzem bem em mock; `clean_redis` isola sem container novo. |
| **Mock de LLM, Twilio, psutil** | Provedores externos são lentos, caros e não determinísticos; integração foca regras de negócio e persistência. |
| **Retrievers aceitam `conn=pgvector_conn`** | Refactor de `KnowledgeBaseRetriever` e `LongTermMemory` para injetar conexão asyncpg da transação de teste — RAG testável com rollback. |
| **API: override de auth + JWT real** | Maioria usa `auth_client` (rápido); alguns testes usam `auth_headers` para validar pipeline completo de token. |

---

## Estrutura de pastas

```text
backend/tests/
├── conftest.py              # pytest_plugins → db_fixtures
├── db_fixtures.py           # Postgres, Redis, factories (Camadas 2+3)
├── unit/                    # Camada 1 — 128 testes
├── integration/
│   ├── conftest.py          # autouse: limpa cache de tabulação
│   └── helpers.py           # OwnerContext, unit_vector, seeds KB
└── api/
    ├── conftest.py          # test_app, client, auth_client
    └── ownership_helpers.py # helpers HTTP compartilhados
```

---

## Referências cruzadas

- Badge e visão resumida: [README.md](../README.md#testes)
- Smoke manual pré-apresentação: [SMOKE_TEST.md](SMOKE_TEST.md)
- Scripts de validação em container (complementares, não substituem pytest): `backend/scripts/validate_*.py`
