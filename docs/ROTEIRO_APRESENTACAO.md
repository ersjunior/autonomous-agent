# Roteiro de apresentação — Autonomous Agent (TCC)

**Público:** banca de IA aplicada  
**Duração alvo:** 15–20 minutos  
**Pré-requisito:** rodar `docs/SMOKE_TEST.md` no dia anterior e 30 min antes da banca.

**URLs fixas (dev padrão):**

| Recurso | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| Login | http://localhost:3000/ (admin@admin.com / admin) |
| Configurações | http://localhost:3000/dashboard/settings |
| Campanhas | http://localhost:3000/dashboard/campaigns |
| Leads | http://localhost:3000/dashboard/leads |
| Métricas | http://localhost:3000/dashboard/metrics |
| Monitoramento (eventos do grafo) | http://localhost:3000/dashboard/monitoring |
| API Swagger | http://localhost:8000/docs |

**Diagramas:** seção *Arquitetura* do [README.md](../README.md) (GitHub ou preview no IDE).

---

## 1. Abertura (~1 min)

### O que fazer
- Slide ou tela inicial com o título do TCC.
- Uma frase de posicionamento; não abrir o terminal ainda.

### O que falar
> "Este trabalho transforma um fluxo clássico de telemarketing em um **agente de IA autônomo**, omnichannel. O diferencial para a banca de **IA aplicada** é a pilha **multi-agente orquestrada por LangGraph**, com **RAG em pgvector**, **LLM e embeddings 100% locais** no Ollama, e síntese de **voz clonada** e **avatar em vídeo** sem depender de APIs pagas — com opção comercial só por configuração."

### O que a banca vê
- Clareza do problema e do foco técnico (IA, não só CRUD).

---

## 2. Arquitetura de IA (~3 min)

### O que fazer
1. Abrir o **README** no GitHub (ou VS Code preview) na seção **Arquitetura**.
2. Mostrar o **diagrama B** (grafo LangGraph) — zoom se possível.
3. Mostrar o **diagrama D** (memória / RAG).
4. Opcional: diagrama **A** (visão geral dos serviços).

### O que falar — Diagrama B (grafo)
> "Cada mensagem entra por `route_message`. O grafo tem **dois agentes de LLM**: primeiro **classifica intenção** e extrai entidades com saída estruturada; depois decide se **escala para humano** ou **gera resposta**. O nó de resposta agora faz **recuperação RAG** no mesmo `user_id` antes de chamar o segundo LLM. Por fim, `send_response` grava o turno no **Redis** (curto prazo, 1 hora) e no **Postgres com embedding** (longo prazo)."

**Nós para citar:** `identify_intent` → `check_escalation` → (`escalate` | `generate_response`) → `send_response`.

### O que falar — Diagrama D (RAG)
> "Memória **curta**: histórico da conversa atual em Redis. Memória **longa**: cada par pergunta-resposta vira vetor com `nomic-embed-text`. Na geração, buscamos conversas **antigas do mesmo cliente** por similaridade de cosseno no pgvector — **não misturamos leads**. Similaridade é `1 menos a distância` do operador `<=>`."

### O que a banca vê
- Separação clara: orquestração × modelos × memória × canais.

### Plano B
- Se o preview Mermaid falhar: usar captura de tela salva dos diagramas ou o PDF exportado do README.

---

## 3. Demo ao vivo — cérebro local + hot-reload (~3 min)

### O que fazer
1. Terminal: `docker exec autonomous-agent-ollama ollama list` (prova local).
2. Navegador: **Configurações** → aba **Texto (LLM)** — mostrar badge `ollama ativo`.
3. Aba **Comportamento**: mostrar `agent_system_prompt`, temperaturas, `rag_top_k`, `rag_similarity_threshold`.
4. Alterar algo leve (ex.: acrescentar uma linha no system prompt) → **Salvar** → mensagem de sucesso.
5. (Opcional) **Monitoramento** — mostrar eventos `intent_detected` / `response_sent` após uma mensagem de teste.

**Mensagem de teste sem Telegram** (terminal):

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

### O que falar
> "O LLM é o **llama3.1 no Ollama**, com GPU quando disponível. Provedores são trocados por variável de ambiente e pela tela **sem reiniciar Docker**: o backend publica versão no Redis e o worker recarrega `app_settings` a cada mensagem."

### O que a banca vê
- Modelo local listado; resposta em português; settings persistem.

### Plano B
- **Ollama lento (cold start):** rodar `make warm-ollama` antes; ou mostrar resposta já copiada no bloco de notas.
- **Timeout:** repetir com mensagem mais curta; verificar `docker logs autonomous-agent-ollama --tail 20`.

---

## 4. Demo ao vivo — RAG (~3 min) ★ principal

### O que fazer (sequência ensaiada)

**Passo 1 — Limpar memória curta** (para não confundir com histórico Redis):

```bash
docker exec autonomous-agent-redis redis-cli DEL chat:RAGTEST
```

**Passo 2 — Rodar validação** (seed + busca + resposta):

```bash
docker cp backend/scripts/validate_rag.py autonomous-agent-worker:/tmp/validate_rag.py
docker exec autonomous-agent-worker python /tmp/validate_rag.py
```

**Passo 3 — Destacar na saída do terminal:**
- Linhas `sim=0.xx` com mensagens antigas (horário, domingo, cancelamento).
- `Bloco RAG injetado? SIM` e trecho do texto "Conversas anteriores relevantes...".
- `Vazamento: NAO (OK)`.
- Resposta final mencionando **9h** ou horário de funcionamento.
- `rag_memories no state: 3` (ou > 0).

**Passo 4 (opcional, UI):** Configurações → Comportamento → `rag_similarity_threshold` = `0.9` → Salvar → rerodar só a query; mostrar 0 memórias. Voltar threshold para `0` ou `0.5`.

### O que falar
> "Gravamos três atendimentos **passados** só no Postgres. O Redis deste contato está **vazio** — não há histórico imediato. A pergunta nova — 'Que horas vocês abrem?' — é semanticamente próxima da pergunta antiga sobre horário. O sistema **recupera** essas linhas, monta um bloco extra no prompt e o LLM responde alinhado ao que já foi dito — **9h às 18h**, sem eu ter colado isso na pergunta. Outro `user_id` no banco **não aparece** na busca: isolamento por cliente."

### O que a banca vê
- Evidência numérica (similaridade) + resposta coerente + isolamento.

### Plano B
- **Script falha:** mostrar log de uma execução bem-sucedida gravada (screenshot) + explicar o código em `graph.py` / `long_term.py`.
- **0 memórias:** conferir `EMBEDDING_DIMENSIONS=768`; rodar seed de novo; threshold muito alto.
- **Resposta genérica:** aumentar `rag_top_k`; baixar threshold; repetir após `warm-ollama`.

---

## 5. Demo ao vivo — voz clonada (~2 min)

### O que fazer
1. http://localhost:3000/dashboard/settings → aba **Áudio (STT/TTS)**.
2. Coluna **Voz de referência**: player do `reference.wav` (se existir).
3. Coluna **Testar voz**: texto padrão ou customizado, ex.:  
   *"Olá! Esta é a minha voz clonada em português, gerada pelo Coqui XTTS."*
4. Clicar **Gerar e ouvir** — aguardar ~10–20 s — player MP3.

### O que falar
> "O TTS é **Coqui XTTS-v2** com **clonagem** a partir de um WAV de referência. O mesmo áudio alimenta campanhas de **voz outbound** via Twilio: o worker gera MP3, expõe URL pública e o TwiML usa `<Play>`. STT local é faster-whisper para a fase inbound de voz, ainda em roadmap."

### O que a banca vê
- Áudio em PT com timbre da amostra.

### Plano B
- **Sem reference.wav:** upload pela UI antes da banca; ou arquivo em `infra/docker/coqui-tts/voices/reference.wav`.
- **Coqui down:** `curl http://localhost:18002/health` (ou porta do `.env`); MP3 pré-gravado no notebook.
- **Erro 503 no teste:** ver smoke test Coqui `model_loaded: true`.

---

## 6. Demo ao vivo — avatar em vídeo (~2 min)

### O que fazer

**Opção A — UI (recomendada na sala):**
1. Configurações → aba **Avatar / Vídeo**.
2. Preview da foto (`default.png` ou upload).
3. Texto de teste → **Gerar e ver vídeo** — aguardar **~20–30 s**.
4. Player `<video>` no navegador.

**Opção B — Telegram (impacto visual):**
- Ter `TELEGRAM_BOT_TOKEN` e `chat_id` de teste no `.env`.
- Vídeo pré-enviado na conversa **ou** comando rápido:

```bash
docker exec autonomous-agent-worker python -c "
import asyncio
from app.services.settings_sync import ensure_settings_fresh_async
from app.services.avatar_video import gerar_video_avatar
from agents.channels.telegram.client import send_telegram_video
from app.core.config import settings

async def go():
    await ensure_settings_fresh_async()
    fn = await gerar_video_avatar('Olá! Demonstração do avatar em português para a banca.')
    path = f'{settings.avatar_video_root}/{fn}'
    await send_telegram_video('SEU_CHAT_ID', path, caption='TCC - Avatar SadTalker')
    print('ok', fn)

asyncio.run(go())
"
```

### O que falar
> "Pipeline: texto → **Coqui** (áudio) → **SadTalker** na **GPU** (lip-sync sobre foto do rosto) → MP4. No outbound, o canal `video` envia o arquivo pelo **Telegram**. Provedor comercial **D-ID** existe, mas o padrão do trabalho é **local**."

### O que a banca vê
- Rosto animado com áudio em português.

### Plano B
- **SadTalker lento ou unhealthy:** MP4 gravado de ensaio anterior; screenshot do Telegram.
- **Sem GPU:** explicar limitação; mostrar endpoint `GET /api/v1/channels/avatar-video/{uuid}.mp4` no Swagger.
- **Falha upload imagem:** usar `default.png` versionado em `infra/docker/sadtalker/avatars/`.

---

## 7. Aplicação de negócio (~2 min)

### O que fazer (rápido, 1–2 telas cada)
1. **Leads** — base importada ou criar campanha com CSV (mapeamento `aux1`, telefones, `telegram_id`).
2. **Campanhas** — canais `whatsapp`, `telegram`, `voice`, `video`; botão iniciar (se Twilio/Telegram configurados).
3. **Métricas** — gráficos por campanha/base.
4. **Devolutiva** — download Excel (ou mencionar geração diária via Celery Beat).

### O que falar
> "A camada de negócio **dispara** o mesmo cérebro de IA: campanha ativa enfileira Celery, cada canal usa o grafo e depois o adaptador — texto, MP3 ou vídeo. **LeadInteraction** rastreia status; **devolutiva** consolida em Excel para o gestor. Isso sustenta o experimento; o contribuição de IA está no grafo, RAG e multimodal local."

### O que a banca vê
- Produto completo, não só notebook.

### Plano B
- Sem Twilio: pular disparo real; mostrar fila no log do worker ou métricas de bases já populadas.

---

## 8. Fechamento (~1 min)

### O que falar
> "Entregamos **quatro canais**, **dois agentes** no LangGraph, **RAG por cliente** no pgvector, stack **open source** com GPU, e **providers agnósticos**. Limitações honestas: inbound de voz/vídeo e Telegram polling não estão no Compose automático; SadTalker exige NVIDIA. Próximos passos: inbound multimodal, fine-tuning, escalar workers."

### O que a banca vê
- Mapa mental fechado: IA + aplicação + limites.

---

## Perguntas prováveis da banca + respostas

### Por que IA local em vez de API paga?
> "Reprodutibilidade para o TCC, **custo zero** em inferência, dados no ambiente controlado e alinhamento com o tema open source. OpenAI/ElevenLabs/D-ID são **plugáveis** pelo `ProviderFactory` quando a operação exige qualidade máxima."

### Como o RAG evita misturar clientes?
> "Toda busca em `get_similar` filtra `WHERE user_id = $1`. O `user_id` do grafo é o identificador do contato no canal (telefone, Telegram id). Outro cliente **nunca** entra no prompt."

### Distância ou similaridade no pgvector?
> "O operador `<=>` devolve **distância** cosseno (0 = igual). Usamos **similaridade = 1 − distância** no SQL e no threshold da UI. Mantemos se `similaridade >= rag_similarity_threshold`."

### Como trocar modelo sem downtime?
> "Variáveis em `.env` ou tela **Configurações** → `app_settings` + Redis `settings_version` → worker/backend recarregam em até ~30 s ou na próxima mensagem. **Não** é preciso `docker compose restart` para prompt/temperatura/provider."

### Quais limitações conhecidas?
> "SadTalker depende de GPU; primeira geração ~20–30 s; RAG ranking pode priorizar frase semanticamente vizinha; voz outbound Twilio trial pode pedir tecla; embeddings gravados com mensagem+resposta, busca só com mensagem atual."

### E escalabilidade?
> "Arquitetura **stateless** no API, filas Celery horizontais, Postgres e Redis externos. Gargalos: GPU para Ollama/SadTalker, latência do grafo (2 chamadas LLM + RAG). Sharding natural por `user_id` no RAG."

### Por que dois agentes e não um prompt só?
> "Separa **classificação estruturada** (intenção, entidades, confiança, escalação) da **geração livre**, reduz alucinação na rota crítica e permite temperatura 0 na intenção e 0.7 na resposta."

### O RAG substitui o Redis?
> "Não. Redis = conversa **atual** (minutos). pgvector = histórico **entre sessões**. O prompt deixa explícito que o bloco RAG são 'conversas anteriores'."

---

## Plano B — resumo rápido

| Demo | Fallback |
|------|----------|
| Diagramas | Screenshots no README |
| Ollama / grafo | Log + resposta pré-gravada |
| RAG | Saída salva de `validate_rag.py` |
| Voz | MP3 pré-gerado na UI |
| Avatar | MP4 + print Telegram |
| Campanha | Métricas/devolutiva de base antiga |

---

## Checklist do apresentador (5 min antes)

- [ ] `docs/SMOKE_TEST.md` todo verde
- [ ] `make warm-ollama` executado
- [ ] `redis-cli DEL chat:RAGTEST`
- [ ] `validate_rag.py` copiado no worker
- [ ] Abas do browser abertas: Settings, README diagramas, (opcional) Telegram
- [ ] Áudio do notebook testado; volume OK
- [ ] MP4/MP3 de fallback na pasta `docs/demo-assets/` (opcional)

---

*Última revisão alinhada ao código: grafo com RAG em `generate_response`, script `backend/scripts/validate_rag.py`, URLs e comandos do `Makefile` na raiz do repositório.*
