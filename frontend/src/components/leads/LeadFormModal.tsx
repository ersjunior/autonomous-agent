"use client";

import { FormEvent, useEffect, useState } from "react";
import { updateLead } from "@/lib/api-entities";
import { FIXED_LEAD_COLUMNS, type Lead } from "@/lib/types/leads";
import { Modal } from "@/components/ui/Modal";

interface LeadFormModalProps {
  open: boolean;
  lead: Lead | null;
  readOnly: boolean;
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}

export function LeadFormModal({
  open,
  lead,
  readOnly,
  onClose,
  onSaved,
  onError,
}: LeadFormModalProps) {
  const [form, setForm] = useState<Partial<Lead>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (lead) {
      setForm({ ...lead });
    }
  }, [lead]);

  if (!lead) {
    return null;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (readOnly) {
      return;
    }
    setSubmitting(true);
    try {
      await updateLead(lead!.id, {
        id_cliente: form.id_cliente ?? null,
        nome_cliente: form.nome_cliente,
        cpf_cliente: form.cpf_cliente ?? null,
        email_cliente: form.email_cliente ?? null,
        telefone_1: form.telefone_1 ?? null,
        telefone_2: form.telefone_2 ?? null,
        telefone_3: form.telefone_3 ?? null,
        aux_values: form.aux_values ?? {},
      });
      onSaved();
      onClose();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Erro ao salvar lead.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title={readOnly ? "Visualizar lead" : "Editar lead"}
      onClose={onClose}
      wide
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {FIXED_LEAD_COLUMNS.map((col) => (
          <div key={col.key}>
            <label className="mb-2 block text-sm font-medium text-foreground">
              {col.label}
            </label>
            <input
              type="text"
              required={col.key === "nome_cliente" && !readOnly}
              disabled={readOnly}
              value={(form[col.key as keyof Lead] as string | undefined) ?? ""}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, [col.key]: e.target.value || null }))
              }
              className="input-field disabled:opacity-70"
            />
          </div>
        ))}

        {!readOnly && (
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? "Salvando..." : "Salvar lead"}
          </button>
        )}
      </form>
    </Modal>
  );
}
