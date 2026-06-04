# Smoke test pré-apresentação — Autonomous Agent

Checklist objetivo para rodar **no dia da banca** (e no dia anterior).  
Ambiente assumido: raiz do repositório, `.env` copiado de `.env.example`, Docker Desktop com GPU NVIDIA (para SadTalker/Ollama).

**Compose usado pelo Makefile:**

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml
```

---

## 1. Setup inicial

- [ ] **`.env` presente**  
  - Comando: `test -f .env && echo OK` (Git Bash/WSL) ou `dir .env` (PowerShell)  
  - Passou: arquivo existe; `LLM_PROVIDER=ollama`, `EMBEDDING_DIMENSIONS=768`, `AVATAR_PROVIDER=sadtalker`

- [ ] **`make setup` concluído**  
  - Comando: `make setup`  
  - Passou: termina com `✅ Stack pronta!` sem erro; Ollama baixa modelos; migrate OK

- [ ] **Alternativa se já estava no ar:** `make up` + `make pull-models` + `make warm-ollama` + `make migrate`

---

## 2. Containers (10 serviços)

- [ ] **Todos Up / healthy**  
  - Comando: `docker compose --env-file .env -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml ps`  
  - Passou: status `running`; health `healthy` onde aplicável:

| # | Serviço | Container | Health esperado |
|---|---------|-----------|-----------------|
| 1 | postgres | autonomous-agent-postgres | healthy |
| 2 | redis | autonomous-agent-redis | healthy |
| 3 | backend | autonomous-agent-backend | running |
| 4 | frontend | autonomous-agent-frontend | running |
| 5 | worker | autonomous-agent-worker | running |
| 6 | celery-beat | autonomous-agent-celery-beat | running |
| 7 | ollama | autonomous-agent-ollama | healthy (ou running) |
| 8 | faster-whisper | autonomous-agent-faster-whisper | healthy |
| 9 | coqui-tts | autonomous-agent-coqui-tts | healthy |
| 10 | sadtalker | autonomous-agent-sadtalker | healthy |

> **Sem GPU:** SadTalker pode ficar `unhealthy` — vídeo/avatar na banca usa Plano B (MP4 pré-gravado).

---

## 3. Serviços de IA

- [ ] **Ollama — modelos**  
  - Comando: `docker exec autonomous-agent-ollama ollama list`  
  - Passou: lista contém `llama3.1` (ou `OLLAMA_MODEL` do `.env`) e `nomic-embed-text`

- [ ] **Ollama — responde**  
  - Comando: `docker exec autonomous-agent-ollama ollama run llama3.1 "responda apenas: ok" --verbose false`  
  - Passou: resposta em texto (pode demorar no cold start; preferir `make warm-ollama` antes)

- [ ] **faster-whisper**  
  - Comando: `curl -s http://localhost:8001/health`  
  - Se porta remapeada no `.env` (`WHISPER_PORT=18001`): `curl -s http://localhost:18001/health`  
  - Passou: HTTP 200

- [ ] **Coqui TTS**  
  - Comando: `curl -s http://localhost:8002/health` (ou `http://localhost:18002/health` se `COQUI_PORT=18002`)  
  - Passou: JSON com `"model_loaded": true`

- [ ] **SadTalker**  
  - Comando: `curl -s http://localhost:8003/health`  
  - Passou: `"status":"ok"`, `"model_loaded":true`, `"gpu":true` (gpu false = sem NVIDIA)

---

## 4. Banco de dados

- [ ] **Migrations em head**  
  - Comando: `docker exec autonomous-agent-backend alembic current`  
  - Passou: revisão `e5f6a7b8c9d0` (head) ou `(head)` na saída

- [ ] **Coluna embedding 768**  
  - Comando:  
    ```bash
    docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c \
      "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid WHERE c.relname='interactions' AND a.attname='embedding';"
    ```  
  - Passou: `vector(768)` (se `EMBEDDING_DIMENSIONS=1536`, deve ser `vector(1536)`)

- [ ] **Tabelas críticas existem**  
  - Comando:  
    ```bash
    docker exec autonomous-agent-postgres psql -U postgres -d autonomous_agent -c "\dt"
    ```  
  - Passou: inclui `users`, `agents`, `campaigns`, `campaign_channels`, `lead_bases`, `lead_base_channels`, `leads`, `lead_interactions`, `interactions`, `app_settings`

---

## 5. API e frontend

- [ ] **Backend Swagger**  
  - Comando: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs` (PowerShell: abrir no browser)  
  - Passou: `200`

- [ ] **Frontend**  
  - Comando: abrir http://localhost:3000  
  - Passou: página carrega (login ou redirect)

- [ ] **Login admin**  
  - Credenciais: `admin@admin.com` / `admin`  
  - Passou: entra no dashboard sem 401

- [ ] **Configurações**  
  - URL: http://localhost:3000/dashboard/settings  
  - Passou: abas Texto / Comportamento / Áudio / Avatar; badge `ollama ativo` (ou provider configurado); **sem** banner vermelho persistente

---

## 6. Testes funcionais (IA)

- [ ] **reference.wav**  
  - Comando: `docker exec autonomous-agent-coqui-tts test -f /voices/reference.wav && echo OK`  
  - Ou arquivo em `infra/docker/coqui-tts/voices/reference.wav` no host  
  - Passou: OK

- [ ] **Imagem do avatar**  
  - Comando: `docker exec autonomous-agent-backend test -f /avatars/default.png && echo OK`  
  - Passou: OK (ou foto enviada pela UI)

- [ ] **Teste de voz na UI**  
  - Ação: Settings → Áudio → Gerar e ouvir  
  - Passou: player toca MP3 (~10–20 s)

- [ ] **Teste de avatar na UI**  
  - Ação: Settings → Avatar / Vídeo → Gerar e ver vídeo  
  - Passou: `<video>` reproduz MP4 (~20–30 s)

- [ ] **RAG — validate_rag**  
  - Comandos:  
    ```bash
    docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
    docker cp backend/scripts/validate_rag.py autonomous-agent-worker:/tmp/validate_rag.py
    docker exec autonomous-agent-worker python /tmp/validate_rag.py
    ```  
  - Passou:  
    - `Bloco RAG injetado? SIM`  
    - `Vazamento: NAO (OK)`  
    - `rag_memories no state:` ≥ 1  
    - Resposta menciona horário/9h ou contexto das seeds

- [ ] **Grafo rápido (opcional)**  
  - Comando:  
    ```bash
    docker exec autonomous-agent-worker python -c "import asyncio; from agents.orchestrator.router import route_message; print(asyncio.run(route_message('teste','telegram','SMOKE'))['response'][:200])"
    ```  
  - Passou: texto não vazio

---

## 7. Integrações opcionais (demo outbound)

- [ ] **Telegram** (vídeo no celular)  
  - `.env`: `TELEGRAM_BOT_TOKEN` preenchido  
  - Passou: `docker exec autonomous-agent-worker python -c "from app.core.config import settings; print(bool(settings.telegram_bot_token))"` → `True`

- [ ] **Twilio / voz outbound**  
  - `.env`: `TWILIO_*`, `PUBLIC_BASE_URL` **sem barra final**  
  - Túnel: Cloudflare (`trycloudflare.com`) ou ngrok  
  - Passou: `curl -s -o /dev/null -w "%{http_code}" $PUBLIC_BASE_URL/docs` → 200 (URL pública alcança o backend)

---

## 8. Pré-aquecimento (recomendado 30 min antes)

```bash
make warm-ollama
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
```

Abrir no browser (abas fixas):

1. http://localhost:3000/dashboard/settings  
2. README → seção Arquitetura (diagramas)  
3. http://localhost:8000/docs  

---

## Troubleshooting rápido

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `vector dimension mismatch` / erro em embedding | `EMBEDDING_DIMENSIONS` ≠ coluna | Alinhar `.env` a 768; `make migrate` em DB limpo ou migration `a7b8c9d0e1f2` |
| Ollama 500 / `temperature must be float32` | Settings numéricos como string no DB | Corrigido em `settings_service`; UI → Salvar de novo; ou seed settings |
| UI "Sessão expirada" / 401 | JWT expirado | Login de novo em `/` |
| Configurações não carregam | Backend down ou CORS/API URL | `NEXT_PUBLIC_API_URL=http://localhost:8000`; restart frontend |
| Coqui não sobe / `model_loaded: false` | Build longo ou sem WAV | Aguardar health; colocar `reference.wav`; ver logs `docker logs autonomous-agent-coqui-tts` |
| Coqui TOS | Variável não aceita | `COQUI_TOS_AGREED=1` no compose (já definido) |
| SadTalker unhealthy | Sem GPU / driver | Usar MP4 pré-gravado na apresentação; ou NVIDIA Toolkit + restart |
| Avatar teste 503 | SadTalker down ou imagem ausente | `/avatars/default.png`; `curl localhost:8003/health` |
| Voz teste falha | reference.wav ausente | Upload na UI ou arquivo em `coqui-tts/voices/` |
| ngrok "interstitial" / Twilio não busca URL | Página intermediária ngrok | Usar **Cloudflare Tunnel**; header `ngrok-skip-browser-warning` não ajuda Twilio |
| `PUBLIC_BASE_URL` com `/` no final | Twilio concatena path errado | Remover barra final no `.env` |
| RAG retorna 0 memórias | Threshold alto ou sem seed | `rag_similarity_threshold=0`; rodar `validate_rag.py` |
| RAG "vazamento" | Bug filtro user_id | Verificar query com `user_id` — deve estar `WHERE user_id = $1` |
| Redis mascarando RAG | Histórico curto na demo | `redis-cli DEL chat:RAGTEST` antes do script |
| `make setup-opensource` falha profile | Profile removido | Usar `make setup` com `.env` padrão |
| Pillow / openpyxl import error | Imagem antiga do container | `docker compose build --no-cache backend worker` |
| Frontend métricas quebram | `recharts` não instalado | `docker compose exec frontend npm install` (dev) |
| Telegram inbound não responde | Polling não está rodando | Processo manual `TelegramHandler().start()` — fora do smoke obrigatório |
| Twilio trial pede tecla | Conta trial | Explicar na banca; usar áudio/UI em vez de discagem |

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

*Comandos validados contra `Makefile`, `docker-compose.yml` e `backend/scripts/validate_rag.py` na raiz do repositório.*
