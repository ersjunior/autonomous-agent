# App (App Router)

Rotas do dashboard via **Next.js App Router**. Cada pasta é um segmento de rota; `page.tsx` define a página e `layout.tsx` o layout do segmento.

## Grupos de rota

| Segmento | Conteúdo |
|---|---|
| `(auth)/` | Páginas públicas de autenticação (`login`, `register`) — grupo sem prefixo de URL |
| `dashboard/` | Área autenticada (agentes, canais, leads, campanhas, acionamento, capacidade, conhecimento, tabulações, métricas, monitoramento, configurações) |

O grupo `(auth)` usa `AuthShell` e o `dashboard` usa `DashboardShell` (`src/components/layout/`). O acesso à área autenticada é protegido (ver `src/lib/protection.ts`).
