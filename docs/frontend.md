# Frontend

Dashboard de gestão em Next.js 15 (App Router) + React 19 + TypeScript, estilizado com Tailwind CSS.

## Estrutura
frontend/src/

├── app/

│   ├── (auth)/login, register      # Telas de autenticação

│   └── dashboard/

│       ├── layout.tsx              # Shell do dashboard + navegação

│       ├── page.tsx                # Visão geral

│       └── leads, channels, agents, campaigns, tabulacoes,

│           activation, knowledge, monitoring, metrics,

│           capacity, settings      # Telas de gestão

├── components/

│   ├── layout/                     # DashboardShell, AuthShell

│   ├── ui/                         # Modal, Badge, PageHeader, ...

│   ├── leads/                      # Wizard de CSV, tabelas, formulários

│   └── providers/                  # ThemeProvider (tema claro/escuro)

└── lib/

├── api*.ts                     # Clientes da API (entities, activation, monitoring, tunnel)

├── credentials.ts, protection.ts, csv.ts

└── types/                      # Tipagens por domínio

## Telas do dashboard

| Tela | Função |
|---|---|
| Visão geral | Contadores: agentes, canais ativos, leads, campanhas ativas |
| Leads | Bases (importadas/manuais), importação via CSV, CRUD de leads |
| Canais | CRUD de canais WhatsApp/Telegram/Voz e suas credenciais |
| Agentes | CRUD de agentes ACTIVE/RECEPTIVE; selo de agente de sistema |
| Campanhas | CRUD de campanhas (3 canais), iniciar/parar |
| Tabulações | Catálogo de tabulações (códigos SIP/NEG + customizados) |
| Acionamento | Motor de acionamento, teste ad-hoc e histórico de disparos |
| Conhecimento | Upload/cadastro de documentos da KB, status de ingestão, chunks |
| Monitoramento | Eventos em tempo real (WebSocket) + histórico de conversas + modo humano |
| Métricas | Funil de campanha/base e fila de call center (gráficos) |
| Capacidade | Estimativa de hardware + dimensionamento por Erlang C |
| Configurações | Seleção de providers de IA, prompts/RAG, identidade da empresa, áudio (voz) e túnel |

## Autenticação

O token JWT é guardado no `localStorage` (`access_token`) e enviado nas chamadas à API. A URL da API é configurável via `NEXT_PUBLIC_API_URL` (padrão `http://localhost:8000`).

## Comunicação com o backend

A camada `lib/api*.ts` concentra as chamadas REST por domínio (entidades, acionamento, monitoramento, túnel). O monitoramento em tempo real usa um WebSocket (`/api/v1/monitoring/ws`) que recebe os eventos publicados pelo backend via Redis pub/sub.

Para a API consumida, veja [backend.md](backend.md).
