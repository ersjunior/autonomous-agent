# Dashboard

Área autenticada do produto. Usa `DashboardShell` (`src/components/layout/`) com navegação lateral. Cada subpasta é uma tela.

## Telas

| Rota | Tela |
|---|---|
| `/dashboard` | Visão geral / indicadores |
| `/dashboard/agents` | Configuração de agentes + identidade institucional |
| `/dashboard/channels` | Configuração de canais e webhooks (WhatsApp, Telegram, Voz) |
| `/dashboard/leads` | Upload (CSV) e gestão de leads |
| `/dashboard/campaigns` | Campanhas outbound (modo ATIVO) |
| `/dashboard/activation` | Janelas, cadência e agendamento de acionamento |
| `/dashboard/capacity` | Dimensionamento de capacidade (Erlang C) |
| `/dashboard/knowledge` | Base de conhecimento (upload de documentos para RAG) |
| `/dashboard/tabulacoes` | Tabulações (desfecho do atendimento) |
| `/dashboard/metrics` | Métricas detalhadas |
| `/dashboard/monitoring` | Monitoramento em tempo real (WebSocket) |
| `/dashboard/settings` | Configurações dinâmicas: providers, áudio, identidade, túnel |

Detalhes de cada tela: [`docs/frontend.md`](../../../../docs/frontend.md).
