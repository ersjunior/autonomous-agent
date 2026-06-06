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
| Métricas (incl. fila receptiva) | http://localhost:3000/dashboard/metrics |
| Capacidade (Erlang + estimativa) | http://localhost:3000/dashboard/capacity |
| Tabulações | http://localhost:3000/dashboard/tabulacoes |
| Acionamento (motor + teste + histórico outbound) | http://localhost:3000/dashboard/activation |
| Monitoramento (tempo real + histórico de atendimentos) | http://localhost:3000/dashboard/monitoring |
| API Swagger | http://localhost:8000/docs |

**Diagramas e regras:** seções *Destaques de IA*, *Arquitetura* e *Regras de negócio* do [README.md](../README.md).

**Sumário:** 1 Abertura → 2 Arquitetura → 3 Cérebro local → 4 RAG → **5** Roteamento ATIVO/RECEPTIVO → **5b** Fila + Erlang → **5c** Comportamento receptivo / handoff → **5d** Tabulação / status → **5e** Teste de acionamento → **5f** Ciclo operacional → 6 Propriedade → 7 Voz → 8 Avatar → 9 Negócio → 10 Fechamento.

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

## 5b. Demo ao vivo — Atendimento receptivo: filas + métricas + Erlang (~3–4 min) ★ teoria de filas

### O que fazer

**1. Prova automatizada da fila (terminal)**

```bash
docker exec -e MAX_WEIGHTED_CAPACITY_OVERRIDE=2 autonomous-agent-worker \
  python /workspace/backend/scripts/validate_layer_ra_receptive.py
```

- Passou: com `MAX_WEIGHTED_CAPACITY` baixo, 3º contato entra na fila, mensagem de espera, após liberar capacidade o Beat atende **FIFO** (`[OK]` em fila/processador).

**2. Métricas de call center (navegador)**

- http://localhost:3000/dashboard/metrics — rolar até **Fila de atendimento**  
- Mostrar: tempo médio de espera, **nível de serviço** (alvo em segundos, ex. 20s), taxa de abandono (mensagem honesta se zero: *só voz, sem inbound de voz ainda*).

**3. Capacidade e Erlang C (navegador)**

- http://localhost:3000/dashboard/capacity  
- Mostrar: CPU/RAM do **container** (estimativa), teto global, barra **ativo vs receptivo**, λ/AHT observados, **nível de serviço previsto** e canais necessários para 80/20.

**4. (Opcional) APIs no Swagger**

- `GET /api/v1/metrics/queue?days=1`  
- `GET /api/v1/capacity`

**5. Scripts de regressão (mencionar, não precisa rodar todos ao vivo)**

- `validate_layer_rb_queue.py` — `QueueEntry`, SLA, API de fila  
- `validate_layer_rc_capacity.py` — Erlang C (ex.: A=10 Erlangs, N=14 → SL ≈ 87%), outbound no mesmo teto global

### O que falar

> "Além do roteamento ACTIVE/RECEPTIVE, implementamos **teoria de filas de call center**: capacidade **ponderada compartilhada** entre campanha ativa e receptivo, fila **FIFO** no Redis com histórico em `queue_entries`, e métricas clássicas — tempo de espera, **nível de serviço** configurável e abandono **só para voz** (estrutura pronta; mensageria não abandona). O webhook **não** roda o LLM na thread HTTP: enfileira Celery e responde pelo worker, como um contact center real."

> "A aba **Capacidade** usa **psutil** no container e coeficientes por canal para uma **estimativa** de quantos atendimentos simultâneos cabem — não é benchmark de hardware. O **Erlang C** dimensiona: dado λ (chegadas/h do histórico) e AHT, qual SLA previsto temos e quantos 'agentes' precisaríamos para 80% em 20 segundos. Isso é **planejamento**; quem manda no runtime é o Redis e o scheduler."

### Plano B

- Screenshots das abas Métricas (fila) e Capacidade.  
- Saída salva de `validate_layer_ra_receptive.py` em `docs/demo-assets/`.  
- README — seção **Atendimento receptivo** + diagrama Mermaid do inbound.

### Perguntas prováveis (filas / Erlang) — respostas honestas

| Pergunta | Resposta sugerida |
|----------|------------------|
| **Por que Erlang C?** | É o modelo clássico de filas M/M/c com espera; permite traduzir volume (λ) e tempo de atendimento (AHT) em **probabilidade de espera** e **nível de serviço** — útil para dimensionar equipe/canais antes de gastar infra. No projeto fica em `erlang.py` e na API `/capacity`; **não** substitui o controle da fila em tempo real. |
| **Como medem nível de serviço?** | **Operacional (R-B):** % de `QueueEntry` **ANSWERED** com `wait_seconds` ≤ `SERVICE_LEVEL_TARGET_SECONDS` (default 20s). **Planejamento (R-C):** fórmula Erlang C com o mesmo alvo T e `ERLANG_TARGET_SERVICE_LEVEL` (80%). |
| **A capacidade é real ou estimada?** | **Runtime:** teto `MAX_WEIGHTED_CAPACITY` (pesos por canal) no Redis — isso é **real** no sentido de que bloqueia fila/outbound. **Aba Capacidade:** **estimativa** a partir de CPU/RAM visíveis ao container Docker + `CHANNEL_COST_*`; honestamente não mede GPU do host nem carga de LLM por mensagem. |
| **Abandono na fila?** | Só **voz** (desligou esperando). WhatsApp/Telegram: espera ou atendimento, sem `ABANDONED`. Sem inbound de voz, a taxa na UI tende a zero — deixamos explícito na interface. |
| **Inbound síncrono no webhook?** | **Não.** Webhook/polling enfileira `process_inbound_message`; grafo + envio no worker. Evita timeout do Twilio e unifica com Telegram. |

---

## 5c. Demo ao vivo — Comportamento receptivo: qualificar, escalar e handoff (~3 min) ★ atendimento real

### O que fazer

**1. Receptivo qualificando + RAG (terminal ou WhatsApp/Telegram)**

```bash
docker exec autonomous-agent-redis redis-cli DEL chat:<user_id_teste>
docker exec autonomous-agent-worker \
  python /workspace/backend/scripts/validate_receptive_b1.py
```

- Destacar no output: bloco `RECEPTIVE_BEHAVIOR_PROMPT` injetado; lead vago recebe pergunta de qualificação; dúvida usa RAG (horário 9h–18h no script).

**2. Escalonamento ao vivo (mensagem real)**

- Enviar pelo canal: *"Quero falar com um humano"* **ou** reclamação grave (*"isso é um absurdo, vou processar vocês"*)  
- Mostrar no **Monitoramento** (http://localhost:3000/dashboard/monitoring): evento **Escalada** + contato na seção **Modo humano**

**3. Modo humano — bot para de responder**

- Enviar **outra** mensagem pelo mesmo contato  
- Esperado: **sem** resposta do LLM; no máximo a mensagem ocasional de fila humana (throttle ~5 min)  
- Rodar (opcional): `validate_human_mode_b2.py` — curto-circuito e throttle com `[OK]`

**4. Reativação no painel**

- **Devolver ao bot** na seção Modo humano  
- Nova mensagem → bot atende normalmente de novo

**5. APIs (Swagger ou curl)**

- `GET /api/v1/handoff/active`  
- `POST /api/v1/handoff/reactivate` `{ "channel": "...", "user_id": "..." }`

### O que falar

> "O receptivo não é só FAQ: **responde com RAG** e **qualifica** com perguntas naturais quando o lead está vago — bloco operacional `RECEPTIVE_BEHAVIOR_PROMPT`, separado da personalidade do agente."

> "O escalonamento é **inteligente**: pedido explícito de humano, baixa confiança na classificação, ou **reclamação grave** avaliada pela IA (`complaint_severity`). Reclamação leve o bot tenta resolver."

> "Quando escala, não é só um aviso: entra **modo humano** no Redis — o bot **para** de consumir capacidade e de chamar o LLM. O operador vê quem aguarda no Monitoramento e pode **devolver ao bot**; se ninguém assumir, o **TTL** (4h default) devolve automaticamente. Tabulação **`NEG:ESCALADO`** registra o handoff para a devolutiva."

### Plano B

- Saída de `validate_receptive_b1.py` e `validate_human_mode_b2.py` em `docs/demo-assets/`.  
- Screenshot da seção **Modo humano** no Monitoramento.  
- README — seção **Comportamento do Agente Receptivo** (5c) + diagrama Mermaid.

### Perguntas prováveis (comportamento / handoff)

| Pergunta | Resposta sugerida |
|----------|------------------|
| **Como decide escalar?** | Três gatilhos em `resolve_should_escalate`: `intent=escalate`, `confidence < 0.5`, ou `complaint` com `severity=high`. Reclamação leve fica com o bot. |
| **O que acontece depois que escala?** | Resposta de transferência, tabulação `NEG:ESCALADO` (origem `ESCALATION`), `enter_human_mode` no Redis. Inbound seguinte **não** chama o grafo. |
| **E se ninguém assumir?** | `HUMAN_MODE_TTL_SECONDS` (default 4h) expira a chave; contato volta ao bot. Operador pode reativar antes via painel ou `POST /handoff/reactivate`. |
| **Spamma mensagem de espera?** | Não — throttle `HUMAN_MODE_NOTIFY_INTERVAL_SECONDS` (default 5 min) via chave `human_mode_notified:*`. |
| **Afeta campanha ACTIVE?** | Modo humano é por **contato** (`channel:user_id`). Gatilho vem do inbound; contatos que não escalaram seguem normais. |

---

## 5d. Demo ao vivo — Tabulação / status (~2 min) ★ call center + IA

### O que fazer

**1. Catálogo no dashboard**

- http://localhost:3000/dashboard/tabulacoes  
- Mostrar tabulações **Padrão do sistema**: códigos `SIP:*` (Ocupado, Número inexistente…) e `NEG:*` (Venda, Recusado, Cliente Ausente…).  
- Criar uma tabulação **customizada** (ex.: `CUSTOM:DEMO` / categoria CUSTOMIZADO) — CRUD habilitado; seeds só Visualizar.

**2. Atribuição automática (terminal ou script)**

```bash
docker exec autonomous-agent-backend \
  python /workspace/backend/scripts/validate_tabulacao_t2.py
```

- Destacar linhas `[OK]`: regra `purchase` → `NEG:VENDA`, `nao_atendido` → `NEG:AUSENTE`, camada IA (mock) e colunas na devolutiva Excel.

**3. Devolutiva (opcional, 30 s)**

- Baixar Excel de uma base com interações tabuladas — colunas **Status operacional**, **Tabulação**, **Categoria Tabulação**.

### O que falar

> "Separamos **status operacional** — o que o motor usa para roteamento e cadência — da **tabulação**, que é o vocabulário de **resultado de call center** para o gestor. A atribuição é **híbrida**: primeiro regras (`purchase` vira Venda, sweep sem resposta vira Cliente Ausente); se não resolver, a **IA escolhe um código do catálogo** — saída restrita, não inventa rótulo livre. **Não tabulamos a cada mensagem**, só em momentos de classificação: status terminal ou intent claro."

> "Os códigos **SIP** já estão no seed — Ocupado, Timeout, Número inexistente — mas o **preenchimento automático via telefonia** depende de integração futura: Twilio StatusCallback ou discador Asterisk. Hoje funciona por **regras + IA**; o campo `twilio_call_sid` e `apply_tabulacao(sip_code=…)` estão prontos para quando o discador existir."

### Perguntas prováveis (tabulação)

| Pergunta | Resposta sugerida |
|----------|------------------|
| **Como o status é atribuído?** | Camadas: (1) regras intent/status em `tabulacao_mapping.py`; (2) se não resolver e houver texto, LLM em `tabulacao_agent.py` escolhe **só** códigos do catálogo; (3) SIP futuro. Gravado em `LeadInteraction.tabulacao_id` + `tabulacao_origem`. |
| **E os códigos SIP?** | Catálogo seed pronto (`SIP:486` = Ocupado, etc.). **Automático via hangup/cause code ainda não** — precisa webhook de telefonia. Honestidade: hoje SIP manual/teste via `apply_tabulacao`; produção = discador ou Twilio callbacks. |
| **Tabulação vs status interno?** | Status (`convertido`, `nao_atendido`…) governa grafo, slots e cadência. Tabulação é **relatório** para devolutiva Excel e gestão — pode ser mais granular (ex.: Venda vs Sucesso genérico). |

### Plano B

- Screenshot da aba Tabulações + saída de `validate_tabulacao_t2.py` em `docs/demo-assets/`.  
- README — seção **Tabulação / Status de Atendimento** (5d).

---

## 5e. Demo ao vivo — Teste de acionamento ★ melhor recurso para banca (~2–3 min)

**Por quê:** resposta **síncrona na tela** — sem depender de campanha rodando, janela ou cadência. Ideal para **Telegram** (token no `.env`, lead com `telegram_id`).

### O que fazer
1. http://localhost:3000/dashboard/activation → aba **Teste de acionamento**
2. Agente **ACTIVE** (ex.: `Agente_Ativo`), lead com contato válido, canal **telegram** ou **whatsapp**
3. **Disparar** → aguardar resposta do LLM (dezenas de segundos)
4. Mostrar bloco **Resultado** com texto gerado

### O que falar
> "É o mesmo grafo LangGraph da produção, mas em modo **demonstração**: um disparo, um canal, capacidade global respeitada. Na banca, o Telegram costuma ser o caminho mais estável — a resposta aparece na hora, sem abrir Swagger."

### Plano B
- Saída de `validate_test_dispatch.py` ou screenshot da aba com resultado prévio

---

## 5f. Demo ao vivo — Ciclo operacional completo (~3–4 min)

### Sequência sugerida
1. **Iniciar campanha** — `/dashboard/campaigns` → Iniciar (se Twilio/Telegram configurado)
2. **Monitorar** — `/dashboard/monitoring` → aba **Tempo real** (eventos WebSocket + modo humano se escalar)
3. **Parar campanha** — **Parar** na campanha ativa → `status=paused`, motor desligado por canal
4. **Supervisionar** — aba **Histórico de atendimentos** → **Abrir conversa** → thread user/assistant + metadados (início, duração estimada em chat; voz = indisponível)
5. **Operação outbound** — `/dashboard/activation` → aba **Histórico de acionamentos** → finalizar manual com tabulação (se atendimento aberto)

### O que falar
> "Não é só chatbot: é **sistema de atendimento** — acionar, monitorar em tempo real, **parar** a operação, **supervisionar** conversas (somente leitura) e **encerrar** acionamentos no painel operacional. Dois históricos distintos: **Acionamento** = outbound de campanha; **Monitoramento** = conversas e mensagens, inclusive inbound receptivo."

### Ponto de honestidade
> "Duração de **chamada** de voz ainda não temos — falta callback Twilio. Em chat, a duração é **estimada** pela primeira e última mensagem. Unificamos `+55…` e `whatsapp:+55…` na thread para não partir a conversa."

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

- **Campanhas** — `Agente_Ativo` no `agent_id`; **Iniciar** / **Parar** / retomar.
- **Acionamento** — 3 abas: motor, teste ad-hoc, histórico outbound.
- **Monitoramento** — 2 abas: tempo real, histórico de conversas.
- **Métricas** — campanha/base + **Fila de atendimento** (SLA).
- **Capacidade** — estimativa + Erlang (1 slide se faltar tempo na **5b**; ver também **5f**).
- **Devolutiva** — download Excel (status operacional + tabulação).

### O que falar
> "A camada operacional **dispara** o mesmo grafo; receptivo com **fila** quando o contact center enche; `LeadInteraction`, **tabulação call center**, supervisão de conversas, parar campanha e devolutiva Excel fecham o ciclo para o gestor."

---

## 10. Fechamento (~1 min)

> "Entregamos **RAG ativo**, **roteamento por dono da conversa**, **fila receptiva com métricas de call center**, **comportamento receptivo com handoff humano real** (5c), **tabulação híbrida (regras + IA)** (5d), **ciclo operacional completo** (5f: acionar, testar ao vivo em 5e, parar, supervisionar, finalizar), **dimensionamento Erlang C**, **proteção is_system/IMPORT**, multimodal local e stack reproduzível. Scripts `validate_rag.py`, `validate_phase4_routing.py`, `validate_layer_ra/rb/rc`, `validate_receptive_b1.py`, `validate_human_mode_b2.py`, `validate_tabulacao_t2.py`, `validate_campaign_stop.py`, `validate_test_dispatch.py`, `validate_activation_history.py` e `validate_attendance_history.py` são evidência de regressão para a defesa."

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

### Por que Erlang C num sistema de IA?
> "O gargalo operacional é **concorrência de atendimentos**, não só tokens. Erlang C traduz histórico (λ, AHT) em SLA **previsto** e headroom — mesma linguagem de call center que o gestor entende. A IA decide o texto; a fila decide **quando** há slot."

### Como o agente receptivo decide passar para humano?
> "`resolve_should_escalate` após `identify_intent`: pedido explícito (`escalate`), confiança baixa, ou reclamação **grave** (`complaint_severity=high` no structured output). Leve → bot resolve. Escala → `NEG:ESCALADO` + **modo humano** Redis — bot para de responder até reativação ou TTL."

### O handoff é real ou só mensagem?
> "**Real.** `human_handoff.py` curto-circuita inbound antes do grafo; libera capacidade; mensagem ocasional com throttle. Operador reativa em `/dashboard/monitoring` ou TTL devolve ao bot. Scripts `validate_human_mode_b2.py` provam curto-circuito e reativação."

### Nível de serviço — duas leituras?
> "**R-B (realizado):** % atendidos na fila dentro de T segundos nos `queue_entries`. **R-C (previsto):** Erlang com capacidade N atual. Podem divergir enquanto λ/AHT ainda usam default — deixamos `aht_source` explícito na API."

### Capacidade real vs estimada?
> "**Real no runtime:** pesos no Redis (`MAX_WEIGHTED_CAPACITY`, compartilhado ativo+receptivo). **Estimativa na aba Capacidade:** psutil + `CHANNEL_COST_*` no container — útil para planejar, não para substituir monitoramento de produção."

### Tabulação automática via SIP?
> "Catálogo e API prontos; **automático** depende de Twilio StatusCallback ou discador (Asterisk) — trabalho futuro. Hoje: **regras + IA** em transições significativas; devolutiva Excel já exporta tabulação."

### Como a IA escolhe a tabulação?
> "`tabulacao_agent.py`: structured output com lista fechada de códigos do dono (sistema + custom). Só roda se regras não resolverem e houver texto da conversa — não a cada turno."

---

## Plano B — resumo rápido

| Demo | Fallback |
|------|----------|
| Diagramas | Screenshots / `docs/demo-assets/diagrama-*.png` |
| Ollama / grafo | Log + resposta pré-gravada |
| **RAG** | **`docs/demo-assets/validate-rag-output.txt`** |
| **Roteamento** | **`docs/demo-assets/validate-phase4-routing-output.txt`** + flowchart README |
| **Fila receptiva / Erlang** (5b) | Saída `validate_layer_ra_receptive.py` + screenshots Métricas/Capacidade |
| **Comportamento receptivo / handoff** (5c) | Saída `validate_receptive_b1.py` + `validate_human_mode_b2.py` + screenshot Modo humano |
| **Tabulação / status** (5d) | Saída `validate_tabulacao_t2.py` + screenshot `/dashboard/tabulacoes` |
| **Teste de acionamento** (5e) | Aba Teste em `/dashboard/activation` ou saída `validate_test_dispatch.py` |
| **Ciclo operacional** (5f) | Screenshots Parar campanha + Histórico de atendimentos (thread aberta) |
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
- [ ] Browser: Settings, Agentes, Canais, **Acionamento (3 abas — demo 5e/5f)**, Tabulações (**5d**), Métricas (fila **5b**), Capacidade, **Monitoramento (2 abas — 5c handoff, 5f supervisão)**, README
- [ ] `validate_layer_ra_receptive.py` ensaiado (MAX_WEIGHTED_CAPACITY_OVERRIDE=2)
- [ ] `validate_receptive_b1.py` e `validate_human_mode_b2.py` ensaiados
- [ ] `validate_tabulacao_t2.py` ensaiado
- [ ] `validate_campaign_stop.py`, `validate_test_dispatch.py`, `validate_activation_history.py`, `validate_attendance_history.py` ensaiados
- [ ] (Opcional) `user2@test.com` para isolamento
- [ ] MP3/MP4 fallback

---

*Alinhado ao README (Campanhas parar/retomar, Acionamento 3 abas, Monitoramento 2 abas, Atendimento receptivo + Tabulação), `validate_rag.py`, `validate_phase4_routing.py`, `validate_layer_ra/rb/rc`, `validate_receptive_b1.py`, `validate_human_mode_b2.py`, `validate_tabulacao_t2.py`, `validate_campaign_stop.py`, `validate_test_dispatch.py`, `validate_activation_history.py`, `validate_attendance_history.py`, `conversation_routing.py`, `authorization.py`, seeds em `seed.py`, head Alembic **`k2l3m4n5o6p7`** (ajustes operacionais recentes sem migration nova; `NEG:ESCALADO` via seed).*
