# Leads

Upload e gestão de leads (`/dashboard/leads`). Os leads são organizados em **bases** e alimentam as campanhas do modo ATIVO.

## Recursos

- **Import via CSV** com assistente (`ImportCsvWizard`) e colunas customizáveis (`CustomColumnModal`).
- **Cadastro manual** de lead (`ManualLeadForm` / `LeadFormModal`).
- Tabela com edição/remoção (`LeadsTable`).

O parsing de CSV fica em `src/lib/csv.ts`; a importação no backend em `app/services/csv_import.py`. Cada lead pertence a uma base (`lead_base`) e ao usuário dono.
