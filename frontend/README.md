# Frontend

Dashboard de gestão e monitoramento em **Next.js 15** (App Router) + **TypeScript** + **Tailwind CSS**. Consome a API REST do backend e o WebSocket de monitoramento em tempo real.

## Stack

| Item | Detalhe |
|---|---|
| Framework | Next.js 15 (App Router) |
| Linguagem | TypeScript |
| Estilo | Tailwind CSS (tema claro/escuro) |
| Dados | clientes `fetch` em `src/lib/` + WebSocket de monitoramento |
| Node | 20+ em dev (CI usa Node 22) |

## Estrutura

```
frontend/
├── public/             # assets estáticos
└── src/
    ├── app/            # rotas (App Router): (auth) + dashboard/*
    ├── components/     # componentes React (ui, layout, leads, monitoring…)
    └── lib/            # clientes de API, helpers (csv, credenciais, labels…)
```

## Telas do dashboard

`agents`, `channels`, `leads`, `campaigns`, `activation`, `capacity`, `knowledge`, `tabulacoes`, `metrics`, `monitoring` e `settings`.

## Desenvolvimento

Com a stack completa via Docker (recomendado):

```bash
make up            # sobe backend + frontend + dependências
# frontend em http://localhost:3000  ·  backend em http://localhost:8000
```

Local sem Docker:

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Aponte a base da API com `NEXT_PUBLIC_API_URL` (default para o backend local). Mais detalhes: [`docs/frontend.md`](../docs/frontend.md).
