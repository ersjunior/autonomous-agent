"use client";

import { useState } from "react";
import { deleteLead } from "@/lib/api-entities";
import { leadActionsFor } from "@/lib/protection";
import {
  FIXED_LEAD_COLUMNS,
  sortAuxKeys,
  type Lead,
  type LeadBase,
} from "@/lib/types/leads";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { LeadFormModal } from "@/components/leads/LeadFormModal";

interface LeadsTableProps {
  selectedBase: LeadBase | null;
  columnMapping: Record<string, string>;
  leads: Lead[];
  total: number;
  skip: number;
  limit: number;
  loading: boolean;
  onPageChange: (skip: number) => void;
  onRefresh: () => void;
  onError: (message: string) => void;
}

function cellValue(value: string | null | undefined): string {
  return value?.trim() ? value : "—";
}

export function LeadsTable({
  selectedBase,
  columnMapping,
  leads,
  total,
  skip,
  limit,
  loading,
  onPageChange,
  onRefresh,
  onError,
}: LeadsTableProps) {
  const auxKeys = sortAuxKeys(Object.keys(columnMapping));
  const currentPage = Math.floor(skip / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const canPrev = skip > 0;
  const canNext = skip + limit < total;

  const [viewLead, setViewLead] = useState<Lead | null>(null);
  const [editLead, setEditLead] = useState<Lead | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Lead | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function confirmDeleteLead() {
    if (!deleteTarget) {
      return;
    }
    setDeleting(true);
    try {
      await deleteLead(deleteTarget.id);
      setDeleteTarget(null);
      onRefresh();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Erro ao excluir lead.");
    } finally {
      setDeleting(false);
    }
  }

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
              <th className="whitespace-nowrap px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Ações
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {leads.map((lead) => {
              const actions = leadActionsFor(selectedBase, lead);
              return (
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
                  <td className="whitespace-nowrap px-4 py-4 text-sm">
                    <RecordActionsBar
                      actions={actions}
                      onView={() => setViewLead(lead)}
                      onEdit={() => setEditLead(lead)}
                      onDelete={() => setDeleteTarget(lead)}
                      deleteLoading={deleting && deleteTarget?.id === lead.id}
                    />
                  </td>
                </tr>
              );
            })}
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

      <LeadFormModal
        open={viewLead !== null}
        lead={viewLead}
        readOnly
        onClose={() => setViewLead(null)}
        onSaved={onRefresh}
        onError={onError}
      />

      <LeadFormModal
        open={editLead !== null}
        lead={editLead}
        readOnly={false}
        onClose={() => setEditLead(null)}
        onSaved={onRefresh}
        onError={onError}
      />

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir lead"
        message={`Excluir o lead "${deleteTarget?.nome_cliente}"?`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDeleteLead}
      />
    </div>
  );
}
