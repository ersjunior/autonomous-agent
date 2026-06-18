# Configuração (.env)

Todas as configurações ficam em um arquivo `.env` na raiz, criado a partir do `.env.example`:

```bash
cp .env.example .env
```

No Docker, `DATABASE_URL` e `REDIS_URL` usam os hostnames internos `postgres` e `redis`; para execução local fora do Compose, use `localhost`.

> Parte das configurações de operação (provider de IA, prompts, RAG, voz, handoff) também pode ser alterada em tempo de execução pela tela de Configurações, sem editar o `.env` — veja as settings dinâmicas em [backend.md](backend.md).

## Grupos de variáveis

| Grupo | Variáveis principais | Controla |
|---|---|---|
| Aplicação | `DEBUG`, `SECRET_KEY` | Modo de execução e chave do JWT |
| PostgreSQL | `POSTGRES_*`, `DATABASE_URL`, `TEST_DATABASE_URL`, `POSTGRES_PORT` | Banco da aplicação e de testes |
| Redis / Celery | `REDIS_*`, `CELERY_*` | Cache, broker e backend de resultados |
| Seleção de provider | `LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`, `EMBEDDING_DIMENSIONS` | Escolha do provider por camada (stack OSS local por padrão) |
| Ollama | `OLLAMA_*`, `OLLAMA_KEEP_ALIVE` | LLM e embeddings locais |
| Whisper | `WHISPER_*` | STT local (faster-whisper) |
| Coqui | `COQUI_*` | TTS local e caminho da amostra de voz |
| Motor de acionamento | `ACTIVATION_TIMEZONE`, `CALL_SLOT_TTL_SECONDS`, `CHAT_SLOT_TTL_SECONDS`, `ACTIVE_CONVERSATION_TIMEOUT_HOURS`, `STATUS_TIMEOUT_HOURS` | Camadas de cadência/slots do outbound |
| Fila receptiva | `MAX_WEIGHTED_CAPACITY`, `CHANNEL_WEIGHT_*`, `RECEPTIVE_QUEUE_*` | Teto global e fila de inbound |
| SLA / abandono | `SERVICE_LEVEL_TARGET_SECONDS`, `QUEUE_ABANDON_TIMEOUT_SECONDS` | Nível de serviço e abandono (voz) |
| Modo humano / handoff | `HUMAN_MODE_*`, `HUMAN_HANDOFF_*` | Modo humano, notificação ao operador e sweeps |
| Base de conhecimento | `KB_*` | Upload, chunking e parâmetros de recuperação |
| Agendamento / disponibilidade | `appointment_window_start`, `appointment_window_end`, `appointment_slot_minutes`, `booking_state_ttl_seconds`, `booking_max_offered_slots` | Defaults de slots (Fase D sobrescreve via `availability_rules`); TTL do estado conversacional |
| Voz (telefonia) | `voice_max_response_chars`, `voice_response_max_tokens`, `voice_inbound_mode`, … | Respostas curtas para TTS; turnos inbound por `<Record>` |
| Capacidade / Erlang | `CHANNEL_COST_*`, `CAPACITY_*`, `DEFAULT_AHT_SECONDS`, `ERLANG_TARGET_SERVICE_LEVEL` | Estimativa de capacidade e dimensionamento |
| Alternativas de nuvem (opcionais) | `OPENAI_*`, `ELEVENLABS_*` | Alternativas de nuvem de LLM/STT/TTS (chave exigida só se ativadas) |
| Twilio | `TWILIO_*` | Credenciais de WhatsApp e Voz |
| Túnel | `TUNNEL_MODE`, `CLOUDFLARE_TUNNEL_TOKEN`, `TUNNEL_URL_FILE`, `PUBLIC_BASE_URL` | Exposição pública (webhooks) |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_MODE` | Bot e modo (polling/webhook) |
| Frontend / API | `NEXT_PUBLIC_API_URL`, `FRONTEND_*`, `BACKEND_PORT` | URLs e portas |

## Variáveis essenciais para subir

Para um ambiente local mínimo (IA local, sem canais externos), bastam as configurações de banco, Redis/Celery e os providers locais (já vêm preenchidos como padrão no `.env.example`). As credenciais de canal são necessárias apenas para os canais que você for usar:

| Para usar... | Configure |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN` (e `TELEGRAM_MODE`) |
| WhatsApp | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` |
| Voz | credenciais Twilio (acima) |
| Webhooks externos | `TUNNEL_MODE` + (`PUBLIC_BASE_URL` ou `CLOUDFLARE_TUNNEL_TOKEN` no modo named) |

> O `.env` contém segredos (tokens, chaves) e **não deve ser versionado** — ele já está no `.gitignore`. Apenas o `.env.example` (sem segredos) fica no repositório.

## Notas

- O sistema é **agnóstico de provedor** e a **stack OSS local é o padrão**: `LLM_PROVIDER=ollama`, `STT_PROVIDER=faster_whisper`, `TTS_PROVIDER=coqui` — sem chaves de API. Trocar para uma **alternativa de nuvem (opcional)** é questão de ajustar essas variáveis e fornecer a chave correspondente (`OPENAI_API_KEY`/`ELEVENLABS_API_KEY`), sem alterar código.
- `EMBEDDING_DIMENSIONS` deve ser coerente com o modelo de embeddings usado (padrão `768`, do `nomic-embed-text`).
