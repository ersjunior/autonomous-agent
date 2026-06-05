# Smoke test pré-apresentação — Autonomous Agent

Checklist objetivo para rodar **no dia da banca** (e no dia anterior).  
Ambiente: raiz do repositório, `.env` de `.env.example`, Docker com GPU NVIDIA (SadTalker/Ollama).

**Compose (Makefile):**

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml
```

---

## 1. Setup inicial

- [ ] **`.env` presente**  
  - `LLM_PROVIDER=ollama`, `EMBEDDING_DIMENSIONS=768`, `AVATAR_PROVIDER=sadtalker`  
  - `ACTIVE_CONVERSATION_TIMEOUT_HOURS=24`, `STATUS_TIMEOUT_HOURS=48`

- [ ] **`make setup` concluído**  
  - Passou: `✅ Stack pronta!`; migrate OK

- [ ] **Alternativa:** `make up` + `make pull-models` + `make warm-ollama` + `make migrate` + **restart backend** (lifespan aplica seeds)

---

## 2. Containers (10 serviços)

- [ ] **Todos Up / healthy**  
  - `docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml ps`

| Serviço | Container | Health |
|---------|-----------|--------|
| postgres | autonomous-agent-postgres | healthy |
| redis | autonomous-agent-redis | healthy |
| backend | autonomous-agent-backend | running |
| frontend | autonomous-agent-frontend | running |
| worker | autonomous-agent-worker | running |
| celery-beat | autonomous-agent-celery-beat | running |
| ollama | autonomous-agent-ollama | healthy |
| faster-whisper | autonomous-agent-faster-whisper | healthy |
| coqui-tts | autonomous-agent-coqui-tts | healthy |
| sadtalker | autonomous-agent-sadtalker | healthy |

> Sem GPU: SadTalker pode ficar `unhealthy` — MP4 pré-gravado (`docs/demo-assets/`).

---

## 3. Serviços de IA

- [ ] **Ollama** — `docker exec autonomous-agent-ollama ollama list` → `llama3.1` + `nomic-embed-text`

- [ ] **Ollama responde** — `make warm-ollama` antes da banca

- [ ] **faster-whisper** — `curl -s http://localhost:18001/health` (ou porta do `.env`) → 200

- [ ] **Coqui** — `curl -s http://localhost:18002/health` → `"model_loaded": true`

- [ ] **SadTalker** — `curl -s http://localhost:8003/health` → `"status":"ok"`, `"model_loaded":true`

---

## 4. Banco de dados

- [ ] **Migrations em head**  
  - `docker exec autonomous-agent-backend alembic current`  
  - Passou: revisão **`i0j1k2l3m4n5`** (head)

- [ ] **Tabela `tabulacoes` (T-2)**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT count(*) FROM tabulacoes WHERE is_system = true;"
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "\\d tabulacoes"
  ```  
  - Passou: **16** tabulações `is_system`; colunas `codigo`, `categoria`, `is_terminal`

- [ ] **Colunas de tabulação em `lead_interactions`**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT column_name FROM information_schema.columns WHERE table_name='lead_interactions' AND column_name LIKE 'tabulacao%';"
  ```  
  - Passou: `tabulacao_id`, `tabulacao_origem`, `tabulacao_aplicada_em` (+ `twilio_call_sid` se migration aplicada)

- [ ] **Tabela `queue_entries` (R-B)**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT typname FROM pg_type WHERE typname='queue_entry_status';"
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "\\d queue_entries"
  ```  
  - Passou: enum `WAITING`, `ANSWERED`, `ABANDONED` e tabela `queue_entries`

- [ ] **Embedding 768**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid WHERE c.relname='interactions' AND a.attname='embedding';"
  ```  
  - Passou: `vector(768)`

- [ ] **Seeds: 2 agentes + 4 canais (`is_system`)**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT name, mode::text, is_system FROM agents WHERE name IN ('Agente_Ativo','Agente_Receptivo') ORDER BY name;"
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT name, is_system FROM channels WHERE is_system = true ORDER BY name;"
  ```  
  - **Esperado (agentes):**  
    - `Agente_Ativo` | `ACTIVE` | `t`  
    - `Agente_Receptivo` | `RECEPTIVE` | `t`  
  - **Esperado (canais, 4 linhas):**  
    `Telegram_Agent`, `Video_Agent`, `Voice_Agent`, `WhatsApp_Agent` — todos `is_system = t`

- [ ] **Seeds: 16 tabulações (`is_system`)**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT codigo, nome, categoria FROM tabulacoes WHERE is_system = true ORDER BY codigo LIMIT 5;"
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT count(*) FROM tabulacoes WHERE is_system = true;"
  ```  
  - Passou: **16** linhas; amostra inclui `SIP:200`, `NEG:VENDA`, `NEG:ESCALADO`, etc.

- [ ] **API — listagem inclui seeds** (opcional, confirma visibilidade global)  
  - Login admin → `GET /api/v1/agents` e `GET /api/v1/channels` → JSON contém os nomes acima com `"is_system": true`

- [ ] **Admin existe**  
  ```bash
  docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
    "SELECT email FROM users WHERE email='admin@admin.com';"
  ```  
  - Passou: 1 linha (seeds dependem do admin no lifespan)

---

## 5. API e frontend

- [ ] **Swagger** — http://localhost:8000/docs → 200

- [ ] **Frontend** — http://localhost:3000

- [ ] **Login admin** — `admin@admin.com` / `admin`

- [ ] **Configurações** — http://localhost:3000/dashboard/settings — abas OK; badge provider ativo

- [ ] **`GET /api/v1/metrics/queue` (R-B)**  
  - Login → token → `GET http://localhost:8000/api/v1/metrics/queue?days=1` com `Authorization: Bearer <token>`  
  - Passou: HTTP **200**, JSON com `nivel_servico`, `tempo_medio_espera`, `tamanho_fila_atual`, `service_level_target_seconds`

- [ ] **`GET /api/v1/capacity` (R-C)**  
  - `GET http://localhost:8000/api/v1/capacity` com mesmo token  
  - Passou: HTTP **200**, `resources` (cpu/ram), `estimate`, `erlang`, `usage.global_usage`

- [ ] **`GET /api/v1/tabulacoes` (T-2)**  
  - `GET http://localhost:8000/api/v1/tabulacoes` com mesmo token  
  - Passou: HTTP **200**, JSON com catálogo `SIP:*` e `NEG:*` (`is_system: true`) + customizados do usuário

- [ ] **UI — Métricas, Capacidade e Tabulações**  
  - http://localhost:3000/dashboard/metrics — seção **Fila de atendimento** carrega  
  - http://localhost:3000/dashboard/capacity — recursos + Erlang + uso global  
  - http://localhost:3000/dashboard/tabulacoes — catálogo SIP/negócio com selo **Padrão do sistema**; criar tabulação custom OK

---

## 6. Testes funcionais — IA (scripts de prova)

- [ ] **`validate_rag.py` — recupera memórias e isola por `user_id`**  
  ```bash
  docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
  docker cp backend/scripts/validate_rag.py autonomous-agent-worker:/tmp/validate_rag.py
  docker exec autonomous-agent-worker python /tmp/validate_rag.py
  ```  
  - Passou:  
    - `get_similar` com linhas `sim=` para horário/domingo/cancelamento  
    - `Bloco RAG injetado? SIM`  
    - `Vazamento: NAO (OK)`  
    - `rag_memories no state:` ≥ 1  
    - Resposta de `route_message` coerente com horário (9h–18h)

- [ ] **`validate_phase4_routing.py` — cenários A–E**  
  ```bash
  docker cp backend/scripts/validate_phase4_routing.py autonomous-agent-backend:/tmp/validate_phase4_routing.py
  docker exec autonomous-agent-backend python /tmp/validate_phase4_routing.py
  ```  
  - Passou (cada linha com `OK=True`):  
    - **A** — `lead=None` → `Agente_Receptivo` / RECEPTIVE  
    - **B** — `acionado` + `data_acionamento` → ACTIVE, `open=True`  
    - **C** — `convertido` → RECEPTIVE  
    - **D** — inatividade > `active_conversation_timeout_hours` → RECEPTIVE  
    - **E** — outbound campanha RECEPTIVE → `blocked=True`, `channels=0`  
  - Se `B–E SKIP: nenhuma campanha no banco`: criar campanha no dashboard e rerodar

- [ ] **reference.wav** — `docker exec autonomous-agent-coqui-tts test -f /voices/reference.wav`

- [ ] **Avatar default.png** — `docker exec autonomous-agent-backend test -f /avatars/default.png`

- [ ] **Teste voz UI** — Settings → Áudio → Gerar e ouvir → MP3

- [ ] **Teste avatar UI** — Settings → Avatar → Gerar vídeo → MP4 (~20–30 s)

- [ ] **Grafo rápido (opcional)**  
  ```bash
  docker exec autonomous-agent-worker python -c "import asyncio; from agents.orchestrator.router import route_message; print(asyncio.run(route_message('teste','telegram','SMOKE'))['response'][:200])"
  ```

---

## 6b. Atendimento receptivo (R-A / R-B / R-C)

- [ ] **Webhook inbound enfileira Celery (não LLM síncrono no HTTP)**  
  - WhatsApp: handler enfileira `process_inbound_message.delay` e responde TwiML vazio (sem texto do grafo no webhook).  
  - Conferir logs do worker após mensagem de teste: task `process_inbound_message` executada.

- [ ] **`validate_layer_ra_receptive.py`**  
  ```bash
  docker exec -e MAX_WEIGHTED_CAPACITY_OVERRIDE=2 autonomous-agent-worker \
    python /workspace/backend/scripts/validate_layer_ra_receptive.py
  ```  
  - Passou: fila FIFO, capacidade global, processador Beat (linhas `[OK]`)

- [ ] **`validate_layer_rb_queue.py`**  
  ```bash
  docker exec -e MAX_WEIGHTED_CAPACITY_OVERRIDE=2 autonomous-agent-worker \
    python /workspace/backend/scripts/validate_layer_rb_queue.py
  ```  
  - Passou: `QueueEntry`, SLA, `GET /metrics/queue`

- [ ] **`validate_layer_rc_capacity.py`**  
  ```bash
  docker exec autonomous-agent-worker \
    python /workspace/backend/scripts/validate_layer_rc_capacity.py
  ```  
  - Passou: psutil, Erlang C referência, outbound bloqueado com global cheio, `GET /capacity`

- [ ] **Celery Beat — fila receptiva**  
  - Container `autonomous-agent-celery-beat` em execução  
  - Logs mencionam `process-receptive-queue` / `sweep-queue-abandonment` (opcional: grep nos logs)

---

## 6d. Comportamento do agente receptivo (B-1 + B-2)

- [ ] **`validate_receptive_b1.py` — conduta + escalonamento + tabulação**  
  ```bash
  docker exec autonomous-agent-worker \
    python /workspace/backend/scripts/validate_receptive_b1.py
  ```  
  - Passou: **8/8** cenários — bloco `RECEPTIVE_BEHAVIOR_PROMPT`, `resolve_should_escalate`, reclamação grave vs leve, `NEG:ESCALADO`, RAG, ACTIVE sem bloco receptivo

- [ ] **`validate_human_mode_b2.py` — modo humano (handoff real)**  
  ```bash
  docker exec autonomous-agent-worker \
    python /workspace/backend/scripts/validate_human_mode_b2.py
  ```  
  - Passou: **6/6** cenários — curto-circuito sem LLM, throttle de mensagem ocasional, reativação manual, TTL, fila/capacidade não consumidas

- [ ] **`GET /api/v1/handoff/active` — lista modo humano**  
  - Login admin → token JWT  
  - `GET http://localhost:8000/api/v1/handoff/active` com `Authorization: Bearer <token>`  
  - Passou: HTTP **200**, JSON array (vazio ou com `{ channel, user_id, escalated_at, ttl_seconds }`)

- [ ] **`POST /api/v1/handoff/reactivate` — devolver ao bot**  
  - Após escalar um contato de teste, chamar reactivate com `{ "channel": "telegram", "user_id": "<id>" }`  
  - Passou: `{ "reactivated": true }` e contato some de `/handoff/active`

- [ ] **UI — Monitoramento / Modo humano**  
  - http://localhost:3000/dashboard/monitoring — seção **Modo humano** com lista e botão **Devolver ao bot**  
  - (Opcional ao vivo) Escalar contato → aparece na lista; reativar → próxima mensagem atendida pelo bot

- [ ] **Comportamento verificável (manual ou scripts)**  
  | Cenário | Esperado |
  |---------|----------|
  | Dúvida receptiva / lead vago | Bot responde com RAG e qualifica (pergunta natural) |
  | "Quero falar com um humano" | Transferência + `NEG:ESCALADO` + modo humano ativo |
  | Reclamação grave | Escala + modo humano |
  | Reclamação leve | Bot tenta resolver (não escala) |
  | Nova msg em modo humano | Sem LLM; msg ocasional no 1º envio; throttle na 2ª imediata |
  | Reativação ou TTL | Bot volta a atender normalmente |

> **Alembic:** feature B-1/B-2 **não** adiciona migration — `NEG:ESCALADO` entra via **seed** (`seed_default_tabulacoes`). Head permanece **`i0j1k2l3m4n5`**.

---

## 6c. Tabulação (T-2)

- [ ] **`validate_tabulacao_t2.py`**  
  ```bash
  docker exec autonomous-agent-backend \
    python /workspace/backend/scripts/validate_tabulacao_t2.py
  ```  
  - Passou: linhas `[OK]` para seed catálogo, regras (`NEG:VENDA`, `NEG:AUSENTE`), IA (mock) e colunas **Tabulação** / **Categoria Tabulação** na devolutiva Excel

- [ ] **Devolutiva Excel — colunas de tabulação**  
  - Baixar devolutiva de uma base com `LeadInteraction` tabulada (`GET /api/v1/lead-bases/{id}/devolutiva`)  
  - Passou: cabeçalhos incluem **Status operacional**, **Tabulação**, **Categoria Tabulação**

---

## 7. Proteção, multi-usuário e leads

- [ ] **Proteção API: PUT em registro `is_system` → 403**  
  1. Obter token:  
     ```bash
     curl -s -X POST http://localhost:8000/api/v1/auth/login \
       -H "Content-Type: application/json" \
       -d "{\"email\":\"admin@admin.com\",\"password\":\"admin\"}"
     ```  
  2. `GET /api/v1/agents` com `Authorization: Bearer <token>` → copiar `id` de `Agente_Ativo`  
  3. `PUT /api/v1/agents/<id>` com body `{"name":"SmokeHack"}`  
  - Passou: HTTP **403**, detail contém *Registro padrão do sistema não pode ser editado*

- [ ] **Multi-usuário: globais + próprios**  
  - Registrar `user2@test.com` / senha à escolha (ou usar conta de teste existente)  
  - Login user2 → `GET /api/v1/agents` e `/channels` → vê seeds `is_system`  
  - user2 cria canal/agente próprio → aparece na listagem de user2  
  - Login admin → **não** vê o canal privado de user2  
  - user2: PUT em `Agente_Ativo` → **403**

- [ ] **UI: selo e credenciais mascaradas**  
  - http://localhost:3000/dashboard/agents — seeds com **Padrão do sistema**, só Visualizar  
  - http://localhost:3000/dashboard/channels — 4 seeds; Visualizar → segredos mascarados (não texto plano do `.env`)

- [ ] **Leads: base IMPORT read-only; DELETE da base**  
  - Importar CSV (ou usar base existente `source=IMPORT`) → badge somente leitura; botão editar lead ausente/desabilitado  
  - `PUT /api/v1/leads/<id>` em lead importado → **403**  
  - `DELETE /api/v1/lead-bases/<id>` da base IMPORT (dono) → **204**; leads removidos em CASCADE

- [ ] **Leads MANUAL** — base manual → criar/editar/excluir lead OK

- [ ] **Campanha com agente sistema** — `POST /api/v1/campaigns` com `agent_id` do `Agente_Ativo` → 201

---

## 8. Integrações opcionais (demo outbound)

- [ ] **Telegram** — `TELEGRAM_BOT_TOKEN` no `.env`

- [ ] **Twilio / voz** — `TWILIO_*`, `PUBLIC_BASE_URL` sem barra final; URL pública alcança `/docs` → 200

---

## 9. Pré-aquecimento e Plano B (30 min antes)

```bash
make warm-ollama
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST

# Salvar saídas para apresentação (opcional, não versionar no git)
docker exec autonomous-agent-worker python /tmp/validate_rag.py > docs/demo-assets/validate-rag-output.txt 2>&1
docker exec autonomous-agent-backend python /tmp/validate_phase4_routing.py > docs/demo-assets/validate-phase4-routing-output.txt 2>&1
```

Abas abertas:

1. http://localhost:3000/dashboard/settings  
2. http://localhost:3000/dashboard/agents  
3. http://localhost:3000/dashboard/channels  
4. http://localhost:3000/dashboard/metrics (seção Fila de atendimento)  
5. http://localhost:3000/dashboard/capacity  
6. http://localhost:3000/dashboard/monitoring (Modo humano + feed de eventos)  
7. http://localhost:3000/dashboard/tabulacoes  
8. README → Atendimento receptivo + Comportamento do Agente Receptivo + Tabulação  
8. http://localhost:8000/docs  

---

## Troubleshooting rápido

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| **Seeds ausentes** (0 agentes/canais `is_system`) | Lifespan não rodou ou admin inexistente | Confirmar `admin@admin.com` no DB; restart **backend**; conferir logs `seed_default_channels` / `seed_default_agents` / `ensure_seed_flags` em `main.py` |
| `B–E SKIP` no routing | Sem campanha no banco | Criar campanha + base no dashboard; rerodar script |
| `vector dimension mismatch` | `EMBEDDING_DIMENSIONS` ≠ coluna | `768` + `make migrate` |
| Ollama lento | Cold start | `make warm-ollama` |
| RAG 0 memórias | Threshold alto | `rag_similarity_threshold` baixo; `DEL chat:RAGTEST` |
| PUT seed retorna 200 | Bug/regressão | Deve ser **403** — `authorization.py` + `raise_if_cannot_edit` |
| Campanha RECEPTIVE não envia | Regra de negócio | **Esperado** — cenário E do script |
| Lead IMPORT editável | `source` errado na base | Reimportar; checar API `LeadBaseResponse.source` |
| UI sem selo | Frontend desatualizado | Rebuild frontend; hard refresh |
| `alembic current` antigo | Migração pendente | `make migrate` até `i0j1k2l3m4n5` |
| SadTalker unhealthy | Sem GPU | MP4 em `docs/demo-assets/` |
| Coqui `model_loaded: false` | Build/startup | Aguardar; `reference.wav` |
| 401 na UI | JWT expirado | Login de novo |

---

## Registro de execução (preencher no dia)

| Data | Responsável | Resultado | Observações |
|------|-------------|-----------|-------------|
| | | ☐ OK / ☐ Falhas | |

Itens que falharam:

1.  
2.  

Plano B acionado:

-  

---

*Alinhado ao README (Atendimento receptivo + Comportamento do Agente Receptivo + Tabulação), `validate_rag.py`, `validate_phase4_routing.py`, `validate_layer_ra/rb/rc`, `validate_receptive_b1.py`, `validate_human_mode_b2.py`, `validate_tabulacao_t2.py`, `conversation_routing.py`, `authorization.py`, lifespan em `main.py` / `seed.py`, head Alembic `i0j1k2l3m4n5` (sem migration nova em B-1/B-2; `NEG:ESCALADO` via seed).*
