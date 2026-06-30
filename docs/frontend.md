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

│           capacity, settings, appointments, availability  # Telas de gestão

├── components/

│   ├── layout/                     # DashboardShell, AuthShell

│   ├── ui/                         # Modal, Badge, PageHeader, ...

│   ├── leads/                      # Wizard de CSV, tabelas, formulários

│   └── providers/                  # ThemeProvider (tema claro/escuro)

└── lib/

├── api*.ts                     # Clientes da API (entities, activation, monitoring, tunnel, availability)

├── credentials.ts, protection.ts, csv.ts

└── types/                      # Tipagens por domínio

## Telas do dashboard

| Tela | Função |
|---|---|
| Visão geral | Cards (agentes, canais, leads, campanhas) + **tabela de campanhas** com métricas de funil (§11.1 em `documentacao.md`: Acionáveis, Spin, Contato, CPC, Recusa, Sucesso, Conversão) + gráficos |
| Leads | Bases (importadas/manuais), importação via CSV, CRUD de leads |
| Canais | CRUD de canais WhatsApp/Telegram/Voz e suas credenciais |
| Agentes | CRUD de agentes ACTIVE/RECEPTIVE; selo de agente de sistema |
| Campanhas | CRUD de campanhas (3 canais), iniciar/parar |
| Tabulações | Catálogo de tabulações (códigos SIP/NEG + customizados) |
| Acionamento | Motor de acionamento, teste ad-hoc e histórico de disparos |
| Conhecimento | Upload/cadastro de documentos da KB, status de ingestão, chunks |
| Agendamentos | Agenda interna — listagem, filtros, criação/cancelamento manual (`/dashboard/appointments`) |
| Disponibilidade | Grade semanal de horários (tenant ou agente) para geração de slots (`/dashboard/availability`) |
| Monitoramento | Eventos em tempo real (WebSocket) + histórico de conversas + modo humano |
| Métricas | Página separada (`/dashboard/metrics`): métricas por agente + fila de call center (gráficos) |
| Capacidade | Estimativa de hardware + dimensionamento por Erlang C |
| Configurações | Seleção de providers de IA, prompts/RAG, identidade da empresa, áudio (voz), aba **Túnel & Webhooks** (auto-refresh a cada 10s) e versão **1.0.0** no header |

A versão do produto (`1.0.0`) vem de `frontend/package.json`, exposta via `NEXT_PUBLIC_APP_VERSION` (`next.config.js`). A aba **Túnel & Webhooks** consulta `GET /api/v1/tunnel/status` ao abrir e repete a cada 10s enquanto ativa.

## Autenticação

O token JWT é guardado no `localStorage` (`access_token`) e enviado nas chamadas à API. A URL da API é configurável via `NEXT_PUBLIC_API_URL` (padrão `http://localhost:8000`).

## Comunicação com o backend

A camada `lib/api*.ts` concentra as chamadas REST por domínio (entidades, acionamento, monitoramento, túnel). O monitoramento em tempo real usa um WebSocket (`/api/v1/monitoring/ws`) que recebe os eventos publicados pelo backend via Redis pub/sub.

Para a API consumida, veja [backend.md](backend.md).
