"use client";

import {
  FIXED_LEAD_COLUMNS,
  type Lead,
  sortAuxKeys,
} from "@/lib/types/leads";

interface LeadsTableProps {
  columnMapping: Record<string, string>;
  leads: Lead[];
  total: number;
  skip: number;
  limit: number;
  loading: boolean;
  onPageChange: (skip: number) => void;
}

function cellValue(value: string | null | undefined): string {
  return value?.trim() ? value : "—";
}

export function LeadsTable({
  columnMapping,
  leads,
  total,
  skip,
  limit,
  loading,
  onPageChange,
}: LeadsTableProps) {
  const auxKeys = sortAuxKeys(Object.keys(columnMapping));
  const currentPage = Math.floor(skip / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const canPrev = skip > 0;
  const canNext = skip + limit < total;

  if (loading) {
    return <p className="text-muted-foreground">Carregando leads...</p>;
  }

  if (total === 0) {
    return (
      <div className="glass-card p-8 text-center text-muted-foreground">
        Nenhum lead nesta base.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="glass-card overflow-x-auto">
        <table className="min-w-full divide-y divide-border">
          <thead className="bg-muted/50">
            <tr>
              {FIXED_LEAD_COLUMNS.map((column) => (
                <th
                  key={column.key}
                  className="whitespace-nowrap px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                >
                  {column.label}
                </th>
              ))}
              {auxKeys.map((auxKey) => (
                <th
                  key={auxKey}
                  className="whitespace-nowrap px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                >
                  {columnMapping[auxKey]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {leads.map((lead) => (
              <tr key={lead.id} className="transition hover:bg-muted/30">
                {FIXED_LEAD_COLUMNS.map((column) => (
                  <td
                    key={column.key}
                    className="whitespace-nowrap px-4 py-4 text-sm text-muted-foreground"
                  >
                    {cellValue(lead[column.key as keyof Lead] as string | null | undefined)}
                  </td>
                ))}
                {auxKeys.map((auxKey) => (
                  <td
                    key={auxKey}
                    className="whitespace-nowrap px-4 py-4 text-sm text-muted-foreground"
                  >
                    {cellValue(lead.aux_values?.[auxKey])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          Exibindo {skip + 1}–{Math.min(skip + limit, total)} de {total} leads
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={!canPrev}
            onClick={() => onPageChange(Math.max(0, skip - limit))}
          >
            Anterior
          </button>
          <span className="text-sm text-muted-foreground">
            Página {currentPage} de {totalPages}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={!canNext}
            onClick={() => onPageChange(skip + limit)}
          >
            Próxima
          </button>
        </div>
      </div>
    </div>
  );
}
