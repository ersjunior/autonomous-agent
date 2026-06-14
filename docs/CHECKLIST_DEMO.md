# Checklist Pré-Demo — Autonomous Agent

Guia de subida e validação ponta a ponta antes de uma apresentação ao vivo.
Ambiente: Windows + PowerShell. Banco/serviços via Docker Compose.

> **Regra de ouro:** rode este checklist **inteiro** com folga (idealmente 30+ min antes
> da demo). Os canais externos (WhatsApp/Voz via Twilio) têm latência e sessões que não
> dá para apressar.

---

## 0. Variáveis de túnel no `.env` (conferir uma vez)

A URL pública é **fixa** (named tunnel + domínio próprio). Confirme que o `.env` está em
modo named:

```
TUNNEL_MODE=named
CLOUDFLARE_TUNNEL_TOKEN=eyJ...        (token do túnel; segredo, nunca commitar)
PUBLIC_BASE_URL=https://autonomous-agent.org
```

Conferir sem expor o token:

```powershell
Select-String -Path .env -Pattern "TUNNEL_MODE","PUBLIC_BASE_URL"
```

> Se `TUNNEL_MODE=temporary`, a URL volta a ser aleatória (`trycloudflare.com`) e o webhook
> do WhatsApp quebra. Para a demo, **sempre** `named`.

---

## 1. Subir a stack

```powershell
make setup
```

O `setup` faz, em ordem: sobe os containers (`up -d --build`), espera o Ollama responder,
baixa os modelos (`llama3.1` + `nomic-embed-text`), aquece o modelo e roda as migrations.

> Se já estava no ar e você só quer garantir que está atualizado, `make up` basta (sobe +
> rebuild). Use `make setup` quando subir do zero ou após `make down`.

### 1a. Subir o Telegram polling (passo manual — NÃO está no `make setup`)

O `telegram-polling` é um profile separado. Sem ele, o Telegram **não recebe** mensagens.

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml --profile telegram-polling up -d telegram-polling
```

---

## 2. Confirmar que tudo está de pé

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml ps
```

Devem estar **Up / Healthy** (os essenciais para a demo):

- `backend`
- `worker`
- `celery-beat`
- `postgres`
- `redis`
- `ollama`
- `cloudflared`
- `frontend`
- `telegram-polling` (subido no passo 1a)
- `coqui-tts`, `faster-whisper` (para voz)

### 2a. Modelos do Ollama corretos

```powershell
docker exec autonomous-agent-ollama ollama list
```

Devem aparecer **`llama3.1`** e **`nomic-embed-text`**. Se faltar algum:

```powershell
make pull-models
```

### 2b. Túnel named conectado (URL fixa)

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs --tail=40 cloudflared | Select-String -Pattern "Modo named","Registered tunnel","ERR" -CaseSensitive:$false
```

Esperado: `Modo named` + `Registered tunnel connection`. **Não** deve aparecer a tela de
`--help` em loop.

### 2c. Health pela URL pública (prova o roteamento do túnel)

```powershell
Invoke-RestMethod -Uri "https://autonomous-agent.org/health"
```

Deve retornar o health do backend. Se der erro de DNS/conexão, o túnel não está roteando —
volte ao 2b.

### 2d. Backend resolveu a URL fixa

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs backend | Select-String -Pattern "TUN-1"
```

Esperado: `TUN-1 URL pública resolvida (...): https://autonomous-agent.org`.

---

## 3. Saneamento de estado (evita os silêncios da IA)

### 3a. Liberar leads presos em "modo humano"

Se um lead escalou para humano num teste anterior, ele fica **mudo** (a IA não responde).
Libere os contatos de teste antes da demo:

```powershell
docker exec autonomous-agent-backend python -c "from app.services.human_handoff import exit_human_mode; [exit_human_mode(ch,uid) for ch,uid in [('whatsapp','whatsapp:+5511948660628'),('telegram','5043259127')]]; print('liberados')"
```

> Ajuste os pares `(canal, user_id)` para os contatos que você vai usar na demo.
> Listar quem está preso: `GET /api/v1/handoff/active` (ou a aba Monitoramento no front).

### 3b. Conferir a base de conhecimento (KB)

A KB define a identidade do agente. Para a demo, ela deve ter **só** o conteúdo do caso de
uso que você vai mostrar — **nunca** o texto do próprio TCC (senão o agente "vira" o
exemplo fictício do documento).

- Front → **Conhecimento**: confirme que não há documentos de teste/TCC poluindo.
- Sem KB relevante, o agente atua **neutro** (não inventa identidade) — comportamento
  esperado.

---

## 4. Webhook do Twilio (WhatsApp)

Com a URL fixa, isto é configurado **uma vez** e não muda mais. Só confira que está certo:

- Twilio Console → Messaging → Try it out → **Sandbox settings**
- Campo **"When a message comes in"**:
  `https://autonomous-agent.org/api/v1/channels/webhooks/whatsapp`
- Método: **POST**

### 4a. Sessão do WhatsApp Sandbox ativa

O sandbox tem janela de 24h. Se faz mais de um dia que você não interage, **reabra a
sessão**: do seu celular, mande `join <palavra-chave>` para o número do sandbox
(`+1 415 523 8886`). A palavra-chave está no painel do sandbox.

> O número do sandbox é dos EUA; a entrega para BR funciona mas pode ter latência.
> Para a demo, mande uma mensagem de teste alguns minutos antes para "aquecer" a sessão.

---

## 5. Teste de fumaça — um por canal

Faça cada um e confirme a resposta **antes** da apresentação.

### 5a. Telegram

1. Mande **"oi"** para o bot (`@finance_agent_ai_bot`).
2. Esperado: indicador **"digitando..."** aparece, e a IA responde de forma neutra
   (ou conforme a KB), sem inventar empresa.
3. Mande uma 2ª e 3ª mensagem seguidas — todas devem responder (valida o pool/event loop).

### 5b. WhatsApp

1. Mande **"oi"** para o número do sandbox pelo seu celular.
2. Esperado: **"digitando..."** + resposta da IA.
3. Se ficar mudo: rode o saneamento do **3a** (modo humano) e confira a sessão do **4a**.

### 5c. Voz

1. Dispare/receba a ligação conforme seu fluxo de voz.
2. Esperado: a chamada é atendida e o agente fala.
3. **Outbound voz:** tenta **Coqui XTTS** (português) via `<Play>` MP3; se Coqui/ffmpeg falhar, fallback **Polly pt-BR** (`<Say>`). Mencione o fallback se a demo usar voz.

### 5d. Teste de acionamento (atalho pelo front)

Front → **Acionamento → Teste de acionamento**: escolha agente, lead e canal e dispare.
O resultado (sucesso/erro + resposta gerada) aparece na tela — útil para validar rápido
sem depender do celular.

---

## 6. Acompanhar logs durante a demo (opcional)

Em uma janela separada, deixe os logs do worker rolando para ver o processamento ao vivo:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs -f worker | Select-String -Pattern "sqlalchemy" -NotMatch
```

O `-NotMatch sqlalchemy` corta o ruído de SQL e deixa só tasks/erros.

---

## Pontos de falha conhecidos (referência rápida)

| Sintoma | Causa provável | Correção |
|---|---|---|
| Telegram não recebe | `telegram-polling` não subiu | Passo **1a** |
| WhatsApp envia mas não recebe | Webhook errado / sessão 24h | Passos **4** e **4a** |
| IA fica muda num canal | Lead preso em modo humano | Passo **3a** |
| Agente "vira" empresa fictícia | TCC/teste na KB | Passo **3b** |
| URL do túnel mudou / DNS não resolve | `.env` em `temporary` | Passo **0** (`named`) |
| `.env` novo não aplicou | Container não releu o `.env` | Recriar: `up -d --force-recreate <serviço>` (não só restart) |
| 2ª mensagem trava no canal | (já corrigido — pool por event loop) | — |
| Modelo errado no Ollama | Faltam `llama3.1`/`nomic-embed-text` | Passo **2a** |

---

## Resumo de 1 minuto (cola rápida)

```
1. .env em named?            -> Select-String -Path .env -Pattern "TUNNEL_MODE"
2. make setup                -> sobe tudo + modelos + migrate
3. telegram-polling          -> docker compose ... --profile telegram-polling up -d telegram-polling
4. ps                        -> tudo Up/Healthy
5. /health pela URL fixa     -> Invoke-RestMethod https://autonomous-agent.org/health
6. liberar modo humano       -> exit_human_mode dos leads de teste
7. webhook Twilio + join     -> sessao WhatsApp ativa
8. fumaça: Telegram/WhatsApp/Voz "oi" -> responde + digitando
```
