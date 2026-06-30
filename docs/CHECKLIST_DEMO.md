# Checklist Pré-Demo — Autonomous Agent

Checklist **operacional** para preparar a defesa do TCC. A **sequência da apresentação** (o que falar, tempos, planos B) está em [`ROTEIRO_APRESENTACAO.md`](ROTEIRO_APRESENTACAO.md) — **não duplique o roteiro aqui**.

Ambiente de referência: **Windows + PowerShell**, stack via Docker Compose (`Makefile` na raiz).

**Compose (atalho mental — todos os comandos `docker compose` usam):**

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml
```

---

# PARTE A — PREPARAÇÃO NA VÉSPERA

> Com tempo e margem para errar, corrigir e reensaiar. Faça **1–2 dias antes** da banca.

## A1. Gerar demo-assets (planos B do roteiro)

Pasta: `docs/demo-assets/` (binários gitignored — ver [`demo-assets/README.md`](demo-assets/README.md)).

### A1a. Vídeo backup da ligação ★ crítico

- [ ] Gravar `docs/demo-assets/ligacao-voz-backup.mp4` (MP4 no laptop; não commitar)

**Sequência exata a gravar (tela + áudio):**

1. [ ] Abrir `/dashboard/appointments` — lista **vazia** ou sem o horário que será agendado (zoom legível).
2. [ ] Iniciar gravação de tela **com áudio** da ligação.
3. [ ] Disparar/receber ligação de voz (Twilio).
4. [ ] Cliente: *"Quero marcar um horário."*
5. [ ] Agente oferece **um slot por voz** (por extenso, ex.: *"terça-feira às quatorze horas, serve?"*).
6. [ ] Cliente: *"Sim."* → agente confirma agendamento.
7. [ ] Agente pergunta se há mais alguma coisa; cliente encerra → **desligamento autônomo** (`Hangup`).
8. [ ] Voltar ao navegador → **Atualizar** `/dashboard/appointments` → registro novo visível (`created_by=AGENT`, canal `voice`).
9. [ ] Parar gravação; conferir que áudio e dashboard aparecem no vídeo.

> Plano B do Bloco 3: se a ligação ao vivo falhar em ~45 s, tocar este vídeo.

### A1b. Saída do RAG

- [ ] Limpar Redis de teste (opcional antes de gerar artefato):

```powershell
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
```

- [ ] Copiar e rodar script real `backend/scripts/validate_rag.py`:

```powershell
docker cp backend/scripts/validate_rag.py autonomous-agent-worker:/tmp/validate_rag.py
docker exec autonomous-agent-worker python /tmp/validate_rag.py *> docs/demo-assets/validate-rag-output.txt
```

- [ ] Conferir no `.txt`: `Bloco RAG injetado? SIM`, `Vazamento: NAO (OK)`, resposta com horário 9h–18h.

### A1c. Saída do Erlang (opcional)

```powershell
docker exec -e MAX_WEIGHTED_CAPACITY_OVERRIDE=2 autonomous-agent-worker `
  python /workspace/backend/scripts/validate_layer_rc_capacity.py *> docs/demo-assets/validate-layer-rc-output.txt
```

- [ ] Conferir linhas `[OK]` / SL de referência (~87% para A=10, N=14).

### A1d. Áudio Settings (opcional)

- [ ] Front → **Configurações → Áudio** → Gerar e ouvir → salvar como `docs/demo-assets/voz-demo.mp3`.

---

## A2. Ensaiar apresentação cronometrada

- [ ] Ler [`ROTEIRO_APRESENTACAO.md`](ROTEIRO_APRESENTACAO.md) de ponta a ponta.
- [ ] Ensaio **com cronômetro** (~25 min): Blocos 1→2→**3 (clímax voz)**→*(beat lembrete proativo, cortável)*→4 (RAG+Erlang)→5→6.
- [ ] Validar que a **ligação + agendamento + hangup** funciona de ponta a ponta.
- [ ] Ensaiar **corte do Bloco 5** se passar de min 18 no Bloco 4 (roteiro: pular reforço se `< 8 min` restantes).
- [ ] Ensaiar **Plano B**: trocar ligação pelo vídeo `ligacao-voz-backup.mp4` em ≤30 s.

---

## A3. Sanity final do repositório

- [ ] `make test` (unitários) — verde localmente.
- [ ] (Opcional) `make test-integration` + `make test-api` se houve mudanças recentes.
- [ ] CI GitHub Actions verde na branch que será apresentada.
- [ ] Rodar [`SMOKE_TEST.md`](SMOKE_TEST.md) completo **uma vez** na véspera (não substitui Parte B no dia).

---

## A0. Conferir `.env` (véspera ou antes da Parte B)

- [ ] Túnel em modo **named** (URL fixa para webhooks):

```
TUNNEL_MODE=named
PUBLIC_BASE_URL=https://<seu-dominio>
CLOUDFLARE_TUNNEL_TOKEN=...   # segredo — nunca commitar
```

```powershell
Select-String -Path .env -Pattern "TUNNEL_MODE","PUBLIC_BASE_URL"
```

> `TUNNEL_MODE=temporary` → URL aleatória → webhooks quebram na demo.

### A0b. WhatsApp — templates de lembrete de agendamento (opcional / condicional)

> Só se for **demonstrar lembrete proativo via WhatsApp** fora da janela Meta 24h. Aprovação Meta leva **até ~1 dia** — fazer com antecedência.

- [ ] Templates Meta criados/aprovados: `appointment_reminder` e `appointment_due`
- [ ] Content SID (`HX...`) no `.env`:

```
WHATSAPP_USE_TEMPLATES=true
WHATSAPP_TEMPLATE_MODE=production
WHATSAPP_TEMPLATE_APPOINTMENT_REMINDER=HX...
WHATSAPP_TEMPLATE_APPOINTMENT_DUE=HX...
```

- [ ] Sem template aprovado: lembrete WhatsApp **só funciona dentro da janela 24h** (texto livre). Para demo de lembrete, preferir **voice** ou **Telegram** (não dependem de template).

---

# PARTE B — PREPARAÇÃO NO DIA

> **30–45 min antes** da banca. Rápido, sequencial, à prova de erro. Marque cada `[ ]`.

## B1. Subir ambiente

- [ ] Na raiz do repo:

```powershell
make up
```

> 1ª subida do zero ou após `make down`: use `make setup` (modelos + migrate + warm).

- [ ] Telegram (profile separado — **não** entra no `make setup`):

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml --profile telegram-polling up -d telegram-polling
```

- [ ] Conferir serviços:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml ps
```

Essenciais **Up / Healthy**: `backend`, `worker`, `celery-beat`, `postgres`, `redis`, `ollama`, `cloudflared`, `frontend`, `coqui-tts`, `faster-whisper`, `telegram-polling` (se usar Telegram).

- [ ] Modelos Ollama:

```powershell
docker exec autonomous-agent-ollama ollama list
```

Esperado: `llama3.1` + `nomic-embed-text`. Se faltar: `make pull-models`.

- [ ] Aquecer LLM (reduz latência na demo):

```powershell
make warm-ollama
```

- [ ] Logs cloudflared (túnel named):

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs --tail=40 cloudflared | Select-String -Pattern "Modo named","Registered tunnel","ERR" -CaseSensitive:$false
```

---

## B2. Conferir acessibilidade

- [ ] **Health público** (substitua pela sua `PUBLIC_BASE_URL`):

```powershell
Invoke-RestMethod -Uri "https://<PUBLIC_BASE_URL>/health"
```

- [ ] **Health local:** http://localhost:8000/health

- [ ] Front → **Configurações → aba Túnel & Webhooks**:
  - [ ] Badge **verificado** (health probe OK)
  - [ ] Auto-refresh ~10 s ativo (aba aberta)
  - [ ] URL pública resolvida = `PUBLIC_BASE_URL` do `.env`
  - [ ] URLs de webhook WhatsApp/Telegram copiáveis

- [ ] **Versão 1.0.0** visível no header de Configurações (`NEXT_PUBLIC_APP_VERSION`).

- [ ] Twilio WhatsApp Sandbox (se usar WhatsApp):
  - [ ] Webhook POST → `https://<PUBLIC_BASE_URL>/api/v1/channels/webhooks/whatsapp`
  - [ ] Sessão 24h ativa: enviar `join <palavra-chave>` ao sandbox se necessário

---

## B3. Preparar estado para a demo

### B3a. Modo humano (saneamento)

Leads em modo humano ficam **mudos**. Liberar contatos de teste:

```powershell
docker exec autonomous-agent-backend python -c "from app.services.human_handoff import exit_human_mode; [exit_human_mode(ch,uid) for ch,uid in [('whatsapp','whatsapp:+5511999999999'),('telegram','SEU_TELEGRAM_ID'),('voice','+5511999999999')]]; print('liberados')"
```

> Ajuste `(canal, user_id)` para **seus** contatos. Conferir também: Monitoramento → Modo humano.

### B3b. Base de conhecimento (KB)

- [ ] **Conhecimento** (`/dashboard/knowledge`): conteúdo da **empresa fictícia da demo** — **NÃO** texto do TCC.
- [ ] Documentos relevantes com status **READY** (RAG ativo).

### B3c. Limpar histórico curto (Redis)

Antes do script RAG ao vivo (roteiro Bloco 4a):

```powershell
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
```

> Limpar outros `chat:*` de teste se necessário: `redis-cli KEYS chat:*` (cuidado em prod).

### B3d. ★ Disponibilidade (Fase D) — CRÍTICO para agendamento

- [ ] Abrir http://localhost:3000/dashboard/availability
- [ ] Grade **tenant** (e agente de voz, se override): dias/horários cobrem o slot que você vai demonstrar.
- [ ] Exemplo: se a demo é **terça às 14h**, terça deve estar **ativo** com faixa que inclui 14:00–14:30.
- [ ] **Grade vazia / só manhã** enquanto você demonstra à tarde → **zero slots** → demo quebra.

> Hierarquia: **agente > tenant > default**. Se o agente de voz tem regras próprias, configure **nesse** escopo.

### B3e. ★ Lead válido — CRÍTICO para agendamento

- [ ] Lead existe em `/dashboard/leads` com telefone/`telegram_id` **igual** ao contato que vai ligar/mensagear.
- [ ] Sem `lead_id` resolvido no canal, o bot **não grava** appointment (degrada com mensagem honesta).
- [ ] Lead **não** preso em status terminal que impeça contexto (conferir última interação se inbound).

### B3f. Métricas de campanha (opcional — se for mostrar Bloco 5d)

- [ ] Abrir http://localhost:3000/dashboard — conferir **tabela de campanhas** com dados coerentes.
- [ ] Ideal: ao menos **uma campanha** com **Tentativas**, **Contato** e **CPC** preenchidos (funil legível: Tentativas ≥ Contato ≥ CPC = Sucesso + Recusa).
- [ ] Se a banca **não** for ver métricas, pode pular — **não é ★ crítico**.

---

## B4. Fumaça rápida por canal

### B4a. Telegram

- [ ] Enviar **"oi"** → digitando + resposta.
- [ ] 2ª mensagem seguida → responde (pool OK).

### B4b. WhatsApp

- [ ] Enviar **"oi"** → digitando + resposta.
- [ ] Se mudo: B3a (modo humano) + sessão sandbox (B2).

### B4c. Voz

**Opção 1 — pipeline sem Twilio (rápido):**

```powershell
docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_voice_inbound.py
```

Esperado: STT → grafo → TTS, tempos impressos, `[OK]` no final.

**Opção 2 — ligação curta real (recomendado no dia se possível):**

- [ ] Uma ligação de teste; agente fala (Coqui `<Play>` ou fallback Polly `<Say>`).

### B4d. ★ Fumaça de agendamento (texto)

- [ ] WhatsApp **ou** Telegram: *"Quero agendar"* → escolher slot → confirmar.
- [ ] Conferir registro em `/dashboard/appointments`.
- [ ] **Cancelar** o agendamento de teste na UI (ou PATCH status `CANCELLED`) para **não poluir** a demo ao vivo.

### B4e. Acionamento proativo de agendamento (opcional — bastidores)

> O **clímax continua sendo a ligação** (Bloco 3). Este passo só se quiser **validar** o sweep de lembrete antes da banca ou gravar evidência. **Não é ★ crítico.**

- [ ] Criar appointment com `starts_at` **dentro da janela de lembrete**:
  - Lembrete antecipado (default lead 30 min): ex. **daqui a ~20 min** → cai na janela `[starts_at − 30, starts_at − 5]`
  - Acionamento na hora: ex. **daqui a 2–5 min** → janela `[starts_at, starts_at + 15]`
- [ ] Preencher **`channel`** no appointment (`voice` ou `telegram` — não dependem de template Meta).
- [ ] Confirmar **`celery-beat` Up** (`docker compose … ps`). Se mudou `worker/celery_app.py` (schedule): **recriar o container `celery-beat`**, não só o worker:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d --force-recreate celery-beat
```

- [ ] (Opcional) Observar logs do worker — stats `reminders_sent` / `due_notified` > 0:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs --tail=80 worker | Select-String -Pattern "reminder","due_notified","appointment_reminder" -CaseSensitive:$false
```

- [ ] Cancelar appointment de teste após validar (não poluir demo).

---

## B5. Telas abertas (ordem sugerida do roteiro)

Abas prontas no navegador (login: `admin@admin.com` / `admin`):

| # | URL | Uso |
|---|-----|-----|
| 1 | http://localhost:3000/dashboard/appointments | Clímax — ciclo fechado voz |
| 2 | http://localhost:3000/dashboard | Tabela campanhas / métricas (Bloco 5d, cortável) |
| 3 | http://localhost:3000/dashboard/availability | Conferir grade (B3d) |
| 4 | http://localhost:3000/dashboard/capacity | Erlang C (Bloco 4b) |
| 5 | http://localhost:3000/dashboard/knowledge | RAG / KB (Bloco 4a) |
| 6 | http://localhost:3000/dashboard/monitoring | Eventos / handoff (opcional) |
| 7 | http://localhost:3000/dashboard/settings | Túnel (aba) + versão 1.0.0 |
| 8 | http://localhost:8000/docs | Swagger (referência) |

- [ ] Vídeo backup acessível no player (`docs/demo-assets/ligacao-voz-backup.mp4`).
- [ ] Terminal com comando RAG copiado (Bloco 4a) ou `.txt` do plano B aberto.

---

## B6. Logs durante a demo (opcional)

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs -f worker | Select-String -Pattern "sqlalchemy" -NotMatch
```

---

# Pontos de falha conhecidos

| Sintoma | Causa provável | Ação rápida |
|---------|----------------|-------------|
| Túnel / DNS caiu | `temporary` no `.env`; cloudflared down | B1: named + logs cloudflared; `up -d cloudflared` |
| `/health` público falha | Token/domínio; backend down | B1 ps; B2 health local → público |
| Settings → Túnel ≠ verificado | Health probe falhou | Conferir backend + URL; aguardar auto-refresh 10s |
| Webhook não responde | URL errada no Twilio/Telegram | B2: copiar URL da aba Túnel |
| WhatsApp mudo | Modo humano / sessão 24h | B3a; `join` sandbox |
| Telegram mudo | Polling não subiu | B1 profile `telegram-polling` |
| **Ligação não cai em ~45 s** | Twilio/rede/túnel | **Tocar `ligacao-voz-backup.mp4`** (roteiro Plano B) |
| Agente não oferece horário | **Grade availability vazia/errada** | **B3d** — ajustar `/availability` |
| Agendamento não grava | **Sem lead_id** para o contato | **B3e** — cadastrar lead com mesmo número/id |
| Slot sempre ocupado | Appointment de teste não limpo | Cancelar em `/appointments` (B4d) |
| RAG vazio na demo | KB sem READY / threshold alto | B3b; Settings → RAG thresholds |
| IA lenta na 1ª msg | Ollama frio | `make warm-ollama` (B1) |
| Voz sem áudio Coqui | GPU/serviço coqui-tts | ps coqui-tts; mencionar fallback Polly |
| Agente "vira" empresa fictícia da KB errada | TCC na KB | B3b — remover docs errados |
| **Lembrete de agendamento não dispara** | **`celery-beat` não recriado** após mudar `beat_schedule` em `celery_app.py` | `up -d --force-recreate celery-beat`; conferir job `sweep-appointment-reminders` nos logs do beat |
| Lembrete WhatsApp falha fora 24h | Template Meta não aprovado / SID vazio | A0b — templates `appointment_reminder`/`appointment_due`; ou usar voice/Telegram na demo |

---

# Cola de 1 minuto (dia da banca)

```
1.  .env named?              Select-String .env TUNNEL_MODE, PUBLIC_BASE_URL
2.  make up                 (+ telegram-polling profile se Telegram)
3.  make warm-ollama        latência
4.  ps                      tudo Up/Healthy
5.  /health público         Invoke-RestMethod https://<PUBLIC_BASE_URL>/health
6.  Settings → Túnel        status verificado + v1.0.0
7.  B3d availability        slots no horário da demo ★
8.  B3e lead                número/id bate com contato ★
9.  B3a liberar humano      exit_human_mode
10. B4 fumaça               TG/WA "oi" + agendamento teste → cancelar
11. B3f dashboard           tabela campanhas coerente (se Bloco 5d)
12. Abas prontas            appointments, dashboard, capacity, knowledge
13. Vídeo backup            ligacao-voz-backup.mp4 à mão
14. ROTEIRO                 docs/ROTEIRO_APRESENTACAO.md → apresentar
```

---

*Alinhado a [`ROTEIRO_APRESENTACAO.md`](ROTEIRO_APRESENTACAO.md) e [`documentacao.md`](documentacao.md): clímax voz, acionamento proativo §10.7, métricas §11.1, RAG+Erlang, 797 testes, v1.0.0, availability Fase D, agenda Postgres.*
