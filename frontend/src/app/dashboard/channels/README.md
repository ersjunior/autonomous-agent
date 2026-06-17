# Channels

Configuração dos canais de comunicação (`/dashboard/channels`): **WhatsApp**, **Telegram** e **Voz**.

## O que se configura

- Credenciais e parâmetros por canal (ex.: número Twilio, token do bot Telegram, modo `polling`/`webhook`).
- URLs de **webhook** que devem ser registradas nos provedores (dependem da URL pública do túnel Cloudflare).
- Vínculo de cada canal a um agente.

| Canal | Entrada |
|---|---|
| WhatsApp | Webhook Twilio (`/api/v1/channels/webhooks/whatsapp`) + status de entrega |
| Telegram | Polling (serviço dedicado) ou webhook |
| Voz | TwiML servido pelo backend (Twilio Voice) |

Detalhes: [`docs/canais.md`](../../../../../docs/canais.md) e o túnel em [`docs/infra.md`](../../../../../docs/infra.md).
