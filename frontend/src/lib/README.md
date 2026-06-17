# Lib

Clientes da API e utilitários puros (sem componentes React).

## Clientes de API

| Arquivo | Cobre |
|---|---|
| `api.ts` | Cliente base (fetch + auth JWT) e helpers comuns |
| `api-entities.ts` | Agentes, canais, leads, campanhas e demais entidades |
| `api-monitoring.ts` | Monitoramento em tempo real / atendimentos |
| `api-activation.ts` | Acionamento (janelas, cadência, agendamento) |
| `api-tunnel.ts` | Status e controle do túnel Cloudflare |

## Helpers

| Arquivo | Papel |
|---|---|
| `csv.ts` | Parsing/normalização de CSV (import de leads) |
| `credentials.ts` | Manuseio de credenciais/tokens no cliente |
| `delivery-label.ts` | Rótulos de status de entrega (WhatsApp) |
| `protection.ts` | Guardas de rota / proteção de páginas autenticadas |

A base da API vem de `NEXT_PUBLIC_API_URL`.
