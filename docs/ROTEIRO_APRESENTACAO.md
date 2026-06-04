# Roteiro de apresentação — Autonomous Agent (TCC)

**Público:** banca de IA aplicada  
**Duração alvo:** 15–20 minutos  
**Pré-requisito:** rodar `docs/SMOKE_TEST.md` no dia anterior e 30 min antes da banca.

**URLs fixas (dev padrão):**

| Recurso | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| Login | http://localhost:3000/ (admin@admin.com / admin) |
| Agentes | http://localhost:3000/dashboard/agents |
| Canais | http://localhost:3000/dashboard/channels |
| Campanhas | http://localhost:3000/dashboard/campaigns |
| Leads | http://localhost:3000/dashboard/leads |
| Configurações | http://localhost:3000/dashboard/settings |
| Métricas | http://localhost:3000/dashboard/metrics |
| Monitoramento (eventos do grafo) | http://localhost:3000/dashboard/monitoring |
| API Swagger | http://localhost:8000/docs |

**Diagramas e regras:** seções *Destaques de IA*, *Arquitetura* e *Regras de negócio* do [README.md](../README.md).

---

## 1. Abertura (~1 min)

### O que fazer
- Slide ou tela inicial com o título do TCC.
- Uma frase de posicionamento; não abrir o terminal ainda.

### O que falar
> "Este trabalho transforma um fluxo clássico de telemarketing em um **agente de IA autônomo**, omnichannel. Para a banca de **IA aplicada**, o foco é a pilha **multi-agente LangGraph** com **RAG ativo no pgvector**, modelos **locais na GPU** (Ollama, Coqui, SadTalker) e **regras de domínio**: agentes **ATIVO/RECEPTIVO**, **roteamento por dono da conversa** e **proteção sistema vs usuário** (`is_system`, bases IMPORT)."

### O que a banca vê
- Problema + contribuição técnica (IA + governança leve).

---

## 2. Arquitetura de IA (~3 min)

### O que fazer
1. README — **Destaques de IA** e **Arquitetura**.
2. **Diagrama B** — grafo + `retrieve_similar_memories` + `agent_personality`.
3. **Diagrama D** — Redis + pgvector + roteamento.
4. **Flowchart** em *Regras de negócio* — decisão ACTIVE/RECEPTIVE.

### O que falar — Grafo
> "Entrada única: `route_message`. Nós: `identify_intent` → `check_escalation` → (`escalate` | `generate_response`) → `send_response`. Em `generate_response`, **`LongTermMemory.retrieve_similar_memories`** filtra pelo **mesmo `user_id`** antes do LLM de resposta. No inbound, `inbound_handler` injeta a personalidade do agente de negócio escolhido por `resolve_inbound_agent`."

### O que falar — Roteamento (visão)
> "`conversation_routing.py`: outbound só se `campaign.agent.mode == ACTIVE`; inbound usa a `LeadInteraction` mais recente por `(lead, canal)` — conversa **aberta** se houve `data_acionamento`, status não terminal (`convertido`, `recusou`, `nao_atendido`, `erro`) e último contato dentro de `active_conversation_timeout_hours` (24h)."

### Plano B
- Screenshots dos diagramas (README ou `docs/demo-assets/`).

---

## 3. Demo ao vivo — cérebro local + hot-reload (~3 min)

### O que fazer
1. `docker exec autonomous-agent-ollama ollama list`
2. **Configurações** → Texto / Comportamento (`rag_top_k`, `rag_similarity_threshold`).
3. Salvar alteração leve no prompt (hot-reload via Redis `settings_version`).
4. (Opcional) **Monitoramento** após mensagem de teste.

```bash
docker exec autonomous-agent-worker python -c "
import asyncio
from agents.orchestrator.router import route_message
async def main():
    r = await route_message('Olá, preciso de ajuda com meu pedido', 'telegram', 'DEMO_BANCA')
    print(r.get('response','')[:400])
asyncio.run(main())
"
```

### Plano B
- `make warm-ollama`; resposta pré-gravada.

---

## 4. Demo ao vivo — RAG (~3 min) ★ principal

O script `backend/scripts/validate_rag.py` reproduz o que o grafo faz: seed no pgvector, busca semântica isolada, bloco injetado e `route_message` com Redis limpo.

### Sequência ensaiada

**Passo 1 — Limpar memória curta** (evitar confundir Redis com RAG):

```bash
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
```

**Passo 2 — Rodar validação:**

```bash
docker cp backend/scripts/validate_rag.py autonomous-agent-worker:/tmp/validate_rag.py
docker exec autonomous-agent-worker python /tmp/validate_rag.py
```

**Passo 3 — Destacar na saída (na ordem do script):**

| Etapa do script | O que mostrar |
|-----------------|---------------|
| Seed | 3 pares para `RAGTEST` + 1 interação `OTHERUSER` (prova de isolamento) |
| `get_similar` | Linhas `sim=… dist=…` — pergunta antiga sobre horário próxima de *"Que horas vocês abrem?"* |
| Bloco RAG | `Bloco RAG injetado? SIM` + trecho *"Conversas anteriores relevantes…"* |
| Isolamento | `Vazamento: NAO (OK)` — `OTHERUSER` não aparece na busca de `RAGTEST` |
| Threshold | Com `0.9` → 0 resultados; com `0` → várias memórias (comportamento da UI) |
| `route_message` | Resposta citando **9h–18h** sem colar no prompt; `rag_memories no state:` ≥ 1 |

**Passo 4 (opcional):** Settings → `rag_similarity_threshold` = `0.9` → Salvar → rerodar só a query; voltar threshold.

### O que falar
> "Memória longa só no Postgres; Redis deste `user_id` está vazio. A busca usa **similaridade = 1 − distância cossena** (`<=>` no pgvector) com `WHERE user_id = $1` — mesmo filtro que `retrieve_similar_memories` no nó `generate_response`. O LLM recebe o bloco RAG e responde alinhado ao atendimento passado, **sem vazar** o cliente `OTHERUSER`."

### Plano B
- Arquivo `docs/demo-assets/validate-rag-output.txt` (saída completa de um ensaio bem-sucedido).
- Trecho de `agents/orchestrator/graph.py` (chamada RAG) + `agents/memory/long_term.py` (`get_similar`).

---

## 5. Demo ao vivo — Roteamento de agentes ATIVO/RECEPTIVO (~2–3 min) ★ IA + negócio

### A regra (antes do terminal)

| Fluxo | Regra |
|-------|--------|
| **Outbound** | Só agente **ACTIVE** da campanha dispara; `set_acionamento` na `LeadInteraction`. Agente **RECEPTIVE** → `_send_campaign_message` retorna `blocked=True` (sem envio). |
| **Inbound — conversa aberta** | `is_active_conversation_open`: `data_acionamento` + status não terminal + inatividade ≤ 24h → agente **ACTIVE** (da campanha se for ACTIVE, senão seed `Agente_Ativo`). |
| **Inbound — primeiro contato ou encerrada** | Status terminal, sem acionamento ou inatividade > 24h → agente **RECEPTIVE** (campanha RECEPTIVE ou seed `Agente_Receptivo`). |
| **Lead desconhecido** | `lead=None` → sempre `Agente_Receptivo`. |

**Dono da conversa:** o outbound **ACTIVE** que acionou (`data_acionamento`) mantém o atendimento inbound **enquanto a conversa estiver aberta** — o cliente volta para o mesmo perfil proativo, não para o receptivo genérico. Quando a conversa **encerra** (terminal ou timeout), o próximo inbound é **novo ciclo** → RECEPTIVE.

> Dois timeouts: `active_conversation_timeout_hours` (24h, roteamento) ≠ `status_timeout_hours` (48h, sweep Celery → `nao_atendido`).

### Demo ao vivo

```bash
docker cp backend/scripts/validate_phase4_routing.py autonomous-agent-backend:/tmp/validate_phase4_routing.py
docker exec autonomous-agent-backend python /tmp/validate_phase4_routing.py
```

**Cinco cenários (linhas com `OK=True`):**

| Cenário | O que o script faz | Resultado esperado |
|---------|-------------------|-------------------|
| **A** | `resolve_inbound_agent(session, None, "whatsapp")` | `Agente_Receptivo`, `mode=RECEPTIVE` |
| **B** | `LeadInteraction` `acionado` + `data_acionamento` agora | `open=True`, agente **ACTIVE** |
| **C** | Status `convertido` (terminal) | Agente **RECEPTIVE** |
| **D** | `data_ultimo_contato` > `active_conversation_timeout_hours` | `open=False`, **RECEPTIVE** |
| **E** | Campanha com `Agente_Receptivo` + `_send_campaign_message` | `blocked=True`, `channels=0` |

> Se aparecer `B–E SKIP: nenhuma campanha no banco`, criar uma campanha mínima no dashboard antes da banca (o script precisa de campanha/lead para B–D).

### O que falar
> "Não é só prompt: `resolve_inbound_agent` lê o **estado da conversa** na `LeadInteraction` mais recente por canal. O agente que **iniciou** o relacionamento ativo continua **dono** enquanto `is_active_conversation_open` for verdadeiro — isso evita que um retorno pós-campanha caia no receptivo genérico no meio do funil. O script `validate_phase4_routing.py` é a prova automatizada dos cinco casos."

### Plano B
- `docs/demo-assets/validate-phase4-routing-output.txt` (saída com todos `OK=True`).
- Flowchart do README + log `Inbound routing: open active conversation…` do worker.

---

## 6. Demo ao vivo — Modelo de propriedade (sistema vs usuário) (~2 min)

### O que fazer (navegador + API)

**1. Seeds visíveis (admin)**  
- http://localhost:3000/dashboard/agents — **Agente_Ativo**, **Agente_Receptivo**: selo **Padrão do sistema**, ações só **Visualizar** (descrição longa no modal).  
- http://localhost:3000/dashboard/channels — **WhatsApp_Agent**, **Telegram_Agent**, **Voice_Agent**, **Video_Agent**: mesmo selo; **Visualizar** mostra credenciais **mascaradas** (`lib/credentials.ts`).

**2. Registro próprio com CRUD**  
- Criar agente ou canal com nome próprio → **Editar** e **Excluir** habilitados.

**3. Prova API — 403 em sistema** (Swagger ou terminal):

```bash
# Token admin (JSON)
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@admin.com","password":"admin"}'

# Copiar access_token; listar agentes; PUT no Agente_Ativo (is_system=true)
curl -s -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:8000/api/v1/agents/<UUID_AGENTE_ATIVO>" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"TentativaHack"}'
```

- Passou: **403** com detalhe *"Registro padrão do sistema não pode ser editado"* (`authorization.py` → `raise_if_cannot_edit`).

**4. (Opcional) Multi-usuário**  
- Registrar `user2@test.com` → user2 **vê** seeds + **cria** canal próprio; PUT no seed → 403; não vê campanhas do admin.

**5. Leads (30 s)**  
- Base **IMPORT**: badge somente leitura; **Excluir base** OK. Base **MANUAL**: editar lead.

### O que falar
> "**Multi-tenancy leve**: listagens `is_system OR user_id == eu` (`authorization.py`). Registros padrão são **referência global imutável** — ninguém altera o playbook do sistema, mas qualquer usuário pode montar campanha com `agent_id` de agente sistema (`can_view`). Dados privados ficam isolados por dono."

### Plano B
- Screenshots das telas com selo; print do 403 no Swagger.

---

## 7. Demo ao vivo — voz clonada (~2 min)

1. Settings → **Áudio** — `reference.wav` + **Gerar e ouvir** (~10–20 s).

### O que falar
> "Coqui XTTS com clonagem; outbound voz usa MP3 + Twilio `<Play>`."

### Plano B
- `docs/demo-assets/voz-demo.mp3`

---

## 8. Demo ao vivo — avatar em vídeo (~2 min)

- Settings → **Avatar / Vídeo** → **Gerar e ver vídeo** (~20–30 s), ou MP4/Telegram pré-enviado.

### Plano B
- `docs/demo-assets/avatar-demo.mp4`

---

## 9. Aplicação de negócio (~1 min)

- **Campanhas** — `Agente_Ativo` no `agent_id`; aviso se RECEPTIVE; **Iniciar** (se Twilio configurado).
- **Métricas / devolutiva** — uma tela.

### O que falar
> "A camada operacional **dispara** o mesmo grafo; `LeadInteraction` e devolutiva Excel fecham o ciclo para o gestor."

---

## 10. Fechamento (~1 min)

> "Entregamos **RAG ativo** (script + grafo), **roteamento por dono da conversa** (ACTIVE/RECEPTIVE), **proteção is_system/IMPORT**, multimodal local e stack reproduzível. Scripts `validate_rag.py` e `validate_phase4_routing.py` são evidência de regressão para a defesa."

---

## Perguntas prováveis da banca + respostas

### Por que IA local?
> "Reprodutibilidade, custo zero em inferência, dados no ambiente controlado. OpenAI/ElevenLabs/D-ID via `ProviderFactory` quando necessário."

### Como decidem qual agente atende cada contato?
> "**Dono da conversa** em `conversation_routing.py`: outbound ACTIVE abre com `data_acionamento`; inbound reutiliza esse ACTIVE enquanto `is_active_conversation_open`; senão RECEPTIVE (ou desconhecido → seed `Agente_Receptivo`). Escopo: última `LeadInteraction` por `(lead_id, channel_type)`."

### O agente ativo pode atender inbound?
> "**Sim, mas só** se for a conversa que **ele** (ou a campanha ACTIVE vinculada) abriu e que ainda está **aberta**. **Primeiro contato** ou conversa **encerrada** vai para o **RECEPTIVE** — não mistura funil ativo com triagem passiva."

### Como protegem os registros padrão do sistema?
> "Campo `is_system=true` + `authorization.py`: `can_edit`/`can_delete` falsos para todos; API retorna **403**; UI com selo **Padrão do sistema** e só visualizar. Seeds idempotentes no lifespan (`seed_default_channels`, `seed_default_agents`, `ensure_seed_flags`)."

### O RAG está ativo de verdade?
> "**Sim.** `generate_response` em `graph.py` chama `retrieve_similar_memories` antes do `response_agent`. Prova ao vivo: `validate_rag.py` — `get_similar` com `sim=…`, bloco injetado, `route_message` com `rag_memories` ≥ 1 e `Vazamento: NAO`."

### Como isolam dados entre usuários?
> "Listagens: `or_(is_system, user_id == current_user)` em agents/channels/campaigns/leads; lead_bases via campanha visível. Registros do usuário B **não** aparecem para A. RAG/pgvector: filtro **`user_id` do contato no canal**, não do usuário logado."

### Como o RAG evita misturar clientes?
> "`WHERE user_id = $1` em `get_similar`; `user_id` estável (telefone / `telegram_id`). Script grava `OTHERUSER` e confirma que não vaza na busca de `RAGTEST`."

### ATIVO vs RECEPTIVE — por que dois agentes de campanha?
> "Separa **disparo proativo** (ACTIVE, abre conversa) de **triagem/receptivo** (RECEPTIVE). Distinto dos dois workers LangGraph (intenção vs resposta). `description` vira `agent_personality` no prompt."

### O que é conversa ativa aberta?
> "Todas verdadeiras: existe `LeadInteraction`; `data_acionamento` preenchido; status ∉ {`convertido`,`recusou`,`nao_atendido`,`erro`}; `(agora − data_ultimo_contato) ≤ 24h` (`is_active_conversation_open`)."

### Leads importados podem ser editados?
> "Lead individual: **não** (`LeadBase.source=IMPORT` → 403). **Excluir a base inteira**: sim (`DELETE /lead-bases/{id}`)."

### Dois agentes LangGraph vs dois Agent no banco?
> "LangGraph: pipeline técnico. `Agent` ACTIVE/RECEPTIVE: persona + regra de quem dispara e quem atende inbound."

### Distância ou similaridade no pgvector?
> "Similaridade = 1 − distância cosseno; threshold `rag_similarity_threshold` na UI/`app_settings`."

### Hot-reload de settings?
> "`app_settings` + Redis `settings_version`; worker recarrega sem restart de container."

### Limitações?
> "GPU SadTalker; 2 LLM + RAG por mensagem; Twilio trial; Telegram polling manual; cenário E do script precisa de campanha no DB para B–D."

### Escalabilidade?
> "API stateless, Celery horizontal; gargalos GPU Ollama/SadTalker."

---

## Plano B — resumo rápido

| Demo | Fallback |
|------|----------|
| Diagramas | Screenshots / `docs/demo-assets/diagrama-*.png` |
| Ollama / grafo | Log + resposta pré-gravada |
| **RAG** | **`docs/demo-assets/validate-rag-output.txt`** |
| **Roteamento** | **`docs/demo-assets/validate-phase4-routing-output.txt`** + flowchart README |
| Voz / Avatar | `voz-demo.mp3` / `avatar-demo.mp4` |
| Propriedade UI | Screenshots agentes/canais + print 403 |
| Campanha real | Métricas de base antiga |

**Gerar os `.txt` antes da banca:** rodar os dois scripts uma vez com smoke verde e redirecionar a saída para `docs/demo-assets/` (ver [demo-assets/README.md](demo-assets/README.md)).

---

## Checklist do apresentador (5 min antes)

- [ ] `docs/SMOKE_TEST.md` todo verde
- [ ] `make warm-ollama`
- [ ] `redis-cli DEL chat:RAGTEST`
- [ ] Scripts copiados no container; saídas salvas em `docs/demo-assets/` (Plano B)
- [ ] Campanha existente no DB (para cenários B–D do routing)
- [ ] Browser: Settings, Agentes, Canais, README
- [ ] (Opcional) `user2@test.com` para isolamento
- [ ] MP3/MP4 fallback

---

*Alinhado ao README, `validate_rag.py`, `validate_phase4_routing.py`, `conversation_routing.py`, `authorization.py`, seeds em `seed.py`.*
