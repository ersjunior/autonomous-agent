# Clonagem de voz com Coqui XTTS-v2

O provider `coqui` usa uma amostra WAV de referência (`speaker_wav`) para clonar timbre em português.

## Preparar amostra de voz

1. Grave 10–30 segundos de fala clara, sem ruído de fundo.
2. Exporte como WAV mono, 22050 Hz ou 24000 Hz.
3. Monte no volume Docker `coqui_voices` como `/voices/reference.wav`.

```bash
docker compose -f infra/docker/docker-compose.yml --profile opensource up -d coqui-tts
# Copie seu arquivo para o volume (exemplo)
docker cp minha_voz.wav autonomous-agent-coqui-tts:/voices/reference.wav
```

Configure:

```env
TTS_PROVIDER=coqui
COQUI_BASE_URL=http://coqui-tts:8002
COQUI_VOICE_SAMPLE=/voices/reference.wav
```

## Teste da API

```bash
curl -X POST http://localhost:8002/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"Olá, sou o assistente virtual.","language":"pt","speaker_wav":"/voices/reference.wav"}' \
  --output resposta.wav
```

## Fine-tuning / múltiplas vozes

Para vozes por agente, passe `voice_id` no `TTSProvider.synthesize` com caminhos distintos (`/voices/agente_vendas.wav`). O serviço em `infra/docker/coqui-tts/app.py` aceita qualquer path válido dentro do container.

## Referências

- [Coqui TTS — XTTS-v2](https://github.com/coqui-ai/TTS)
- Provider: `agents/providers/tts/coqui_provider.py`
