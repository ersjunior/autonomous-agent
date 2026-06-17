# Channels

Handlers dos canais de comunicação suportados: **WhatsApp**, **Telegram** e **Voz**. Cada canal converte o formato nativo (webhook/polling/TwiML) no `AgentState` do grafo e cuida do envio da resposta de volta ao cliente.

## Estrutura

```
channels/
├── phone.py              # normalização de números de telefone (E.164)
├── typing_indicator.py   # indicador "digitando..." (Telegram/WhatsApp)
├── whatsapp/             # handler + cliente Twilio (WhatsApp)
├── telegram/             # handler + cliente (polling/webhook)
└── voice/                # handler + TwiML + TTS/STT (Twilio Voice)
```

## Caminho comum (inbound)

1. O canal recebe a mensagem (webhook ou polling).
2. O backend deduplica e enfileira a tarefa Celery, respondendo imediatamente.
3. O worker aciona o indicador "digitando...", invoca o grafo e envia a resposta pela API do canal.

## Indicador "digitando..." (`typing_indicator.py`)

| Canal | Comportamento |
|---|---|
| Telegram | Loop assíncrono reenviando `sendChatAction(typing)` a cada ~4s |
| WhatsApp | Disparo único via API beta da Twilio (requer `message_sid`, validade ~25s) |
| Voz | Não se aplica |

Falhas no indicador são apenas logadas — nunca interrompem o atendimento.

Visão completa dos canais (webhooks, deduplicação, fluxos): [`docs/canais.md`](../../docs/canais.md).
