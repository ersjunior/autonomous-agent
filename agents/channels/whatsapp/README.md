# WhatsApp Channel

Integração de WhatsApp via **Twilio**. Atende tanto o modo RECEPTIVO (responder mensagens recebidas) quanto o ATIVO (campanhas outbound).

## Arquivos

| Arquivo | Papel |
|---|---|
| `handler.py` | Recebe o payload do webhook, monta o `AgentState`, invoca o grafo e dispara o envio da resposta |
| `twilio_client.py` | Cliente Twilio para envio de mensagens, templates e indicador de digitação |

## Inbound (mensagem recebida)

1. A Twilio chama `POST /api/v1/channels/webhooks/whatsapp` (form-data) quando o cliente envia uma mensagem.
2. O backend **deduplica** por `MessageSid` (chave Redis, janela de 24h) — evita processar a mesma mensagem duas vezes em caso de retry da Twilio.
3. Responde imediatamente com **TwiML vazio** (200 OK) e enfileira a tarefa Celery.
4. O worker aciona o indicador "digitando...", processa pelo grafo e envia a resposta **pela API da Twilio** (não no corpo do TwiML).

## Outbound (campanha ativa)

- A tarefa de campanha gera a mensagem pelo grafo (personalidade ACTIVE) e envia pela API da Twilio.
- Fora da janela de sessão de 24h do WhatsApp, é necessário usar **templates aprovados** (HSM) — tratados em `twilio_client.py`.

## Status de entrega

A Twilio notifica mudanças de status (`queued` → `sent` → `delivered` → `read`/`failed`) em `POST /api/v1/channels/webhooks/whatsapp/status`, persistidas para acompanhamento no dashboard.

## Digitando...

Disparo único via API beta da Twilio, exige `message_sid` e tem validade de ~25s (ver `agents/channels/typing_indicator.py`).

## Configuração

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886   # número/sandbox
```

> **Sandbox:** em desenvolvimento, usa-se o Twilio WhatsApp Sandbox, que exige opt-in (`join <palavra-chave>`) e respeita a janela de 24h. O webhook depende de URL pública (túnel Cloudflare — ver [`infra.md`](../../../docs/infra.md)).

Mais detalhes: [`docs/canais.md`](../../../docs/canais.md).
