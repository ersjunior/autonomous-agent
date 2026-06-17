# Source (`src/`)

Código-fonte do dashboard Next.js.

```
src/
├── app/          # rotas (App Router) — grupos (auth) e dashboard/*
├── components/    # componentes React reutilizáveis (ui, layout, domínio)
└── lib/           # clientes de API e utilitários (sem JSX)
```

- **`app/`** define as rotas e o layout; cada pasta é um segmento de rota.
- **`components/`** concentra UI reaproveitável e shells de layout.
- **`lib/`** isola a comunicação com o backend (`api*.ts`) e helpers puros.

Ver [`docs/frontend.md`](../../docs/frontend.md) para a visão geral.
