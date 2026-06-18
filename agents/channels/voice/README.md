# Voice Channel

Canal de **voz por telefonia (PSTN)** via **Twilio Voice**. A fala é sintetizada por TTS e a entrada do cliente é transcrita por STT — ambos agnósticos de provedor (Coqui/faster-whisper local por padrão; alternativas de nuvem opcionais).

## Arquivos

| Arquivo | Papel |
|---|---|
| `handler.py` | Orquestra a chamada: gera o TwiML, sintetiza a fala e processa os turnos |
| `twilio_voice_client.py` | Cliente Twilio Voice (iniciar chamadas, montar respostas) |
| `tts_stt.py` | Síntese (TTS) e transcrição (STT) via `ProviderFactory` |

## TTS (saída de voz)

1. O texto gerado pelo agente é sintetizado em áudio pelo **Coqui XTTS-v2** (português) → MP3 de telefonia.
2. O áudio é reproduzido na ligação via TwiML `<Play>`.
3. **Fallback:** se a síntese falhar, usa-se a voz padrão da Twilio em português — `<Say>` Polly pt-BR.
4. **Cache de speaker:** o serviço Coqui (`infra/docker/coqui-tts/app.py`) mantém latents do sample de voz em cache (path+mtime), reduzindo `speaker_ms` entre sínteses na mesma ligação.

Respostas são limitadas para telefonia (`voice_max_response_chars`, `cap_voice_response_for_telephony`).

## STT (entrada de voz)

- A fala do cliente é transcrita por **faster-whisper** (modelo `large-v3` por padrão).
- A transcrição alimenta o grafo como mensagem de texto.

## Outbound (chamada ativa)

```mermaid
sequenceDiagram
    participant W as Worker
    participant B as Backend
    participant Q as Coqui TTS
    participant T as Twilio
    participant C as Cliente

    W->>B: Gera texto modo ACTIVE
    W->>Q: Sintetiza MP3
    W->>T: Inicia chamada PSTN
    T->>B: Solicita TwiML
    B-->>T: Play MP3 ou Say fallback
    T->>C: Audio na ligacao
```

A campanha de voz inicia a chamada PSTN pela Twilio; o backend serve o TwiML que toca o áudio sintetizado. Para a intenção em voz, usa-se uma **heurística leve** (`agents/workers/voice_intent_heuristic.py`) em vez de uma chamada extra ao LLM, reduzindo latência (incl. `schedule` e `farewell`).

## Inbound conversacional (turnos)

```mermaid
sequenceDiagram
    participant C as Cliente
    participant T as Twilio
    participant B as Backend
    participant W as Worker
    participant STT as faster-whisper

    T->>C: Saudacao TwiML
    C->>T: Fala gravada Record
    T->>B: Callback gravacao
    B->>W: Processa turno grafo
    W->>STT: Transcreve audio
    W->>B: Resposta TwiML Play ou Say
    T->>C: Resposta sintetizada
```

O modo **`record`** (padrão) implementa inbound por turnos: `<Record>` → STT → grafo → TTS → `Redirect` para o próximo turno. **Agendamento por voz:** um slot por vez (sim/não), data/hora por extenso (`format_slot_label_spoken`). **Encerramento autônomo:** `farewell_handler` define `should_hangup`; o backend monta TwiML com `<Hangup/>` (`_build_voice_hangup_twiml` em `channels.py`).

A **transcrição bidirecional em tempo real** (Twilio Media Streams) ainda **não** está conectada — ver [`roadmap.md`](../../../docs/roadmap.md).

## Configuração

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...        # número de voz
TTS_PROVIDER=coqui               # ou elevenlabs (nuvem, opcional)
STT_PROVIDER=faster_whisper      # ou openai (nuvem, opcional)
```

Webhooks de voz ficam sob `/api/v1/channels/webhooks/voice/...` e dependem de URL pública (túnel Cloudflare). Mais detalhes: [`docs/canais.md`](../../../docs/canais.md).
