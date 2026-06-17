# Components

Componentes React reutilizáveis do dashboard.

```
components/
├── ui/           # primitivos: Modal, Badge, Alert, PageHeader, ThemeToggle, CopyButton…
├── layout/        # shells de página: DashboardShell, AuthShell
├── providers/     # contextos React: ThemeProvider (tema claro/escuro)
├── leads/         # domínio de leads: LeadsTable, ImportCsvWizard, LeadFormModal…
├── monitoring/    # domínio de monitoramento: AttendanceConversationModal
└── LoginForm.tsx  # formulário de autenticação
```

## Convenções

- **`ui/`** são primitivos sem regra de negócio (estilizados com Tailwind).
- **`layout/`** define a casca da área autenticada (`DashboardShell`) e de auth (`AuthShell`).
- Componentes de domínio (`leads/`, `monitoring/`) consomem os clientes de `src/lib/`.
