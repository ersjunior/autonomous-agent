"use client";

import { FormEvent, useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { apiFetch } from "@/lib/api";
import {
  FIXED_LEAD_COLUMNS,
  type LeadBase,
  nextAuxKey,
  sortAuxKeys,
} from "@/lib/types/leads";
import { CustomColumnModal } from "./CustomColumnModal";

interface ManualLeadFormProps {
  leadBase: LeadBase | null;
  onSuccess: () => void;
  onColumnMappingUpdated: (mapping: Record<string, string>) => void;
}

export function ManualLeadForm({
  leadBase,
  onSuccess,
  onColumnMappingUpdated,
}: ManualLeadFormProps) {
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [auxValues, setAuxValues] = useState<Record<string, string>>({});
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [showColumnModal, setShowColumnModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!leadBase) {
      setColumnMapping({});
      setFormValues({});
      setAuxValues({});
      return;
    }
    setColumnMapping(leadBase.column_mapping ?? {});
    setFormValues({});
    setAuxValues({});
  }, [leadBase]);

  if (!leadBase) {
    return (
      <div className="glass-card p-6 text-sm text-muted-foreground">
        Selecione uma base de leads para adicionar um lead manualmente.
      </div>
    );
  }

  const auxKeys = sortAuxKeys(Object.keys(columnMapping));

  function updateFixedField(key: string, value: string) {
    setFormValues((current) => ({ ...current, [key]: value }));
  }

  function updateAuxField(key: string, value: string) {
    setAuxValues((current) => ({ ...current, [key]: value }));
  }

  function handleAddColumn(columnName: string) {
    const auxKey = nextAuxKey(columnMapping);
    if (!auxKey) {
      setError(`Máximo de 45 colunas extras atingido.`);
      return;
    }

    const updatedMapping = { ...columnMapping, [auxKey]: columnName };
    setColumnMapping(updatedMapping);
    setAuxValues((current) => ({ ...current, [auxKey]: "" }));
    setError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!leadBase) {
      return;
    }

    setError("");
    setSubmitting(true);

    const nome = formValues.nome_cliente?.trim();
    if (!nome) {
      setError("Nome do cliente é obrigatório.");
      setSubmitting(false);
      return;
    }

    try {
      const mappingChanged =
        JSON.stringify(columnMapping) !== JSON.stringify(leadBase.column_mapping ?? {});

      if (mappingChanged) {
        const mappingRes = await apiFetch(
          `/api/v1/lead-bases/${leadBase.id}/column-mapping`,
          {
            method: "PATCH",
            body: JSON.stringify({ column_mapping: columnMapping }),
          },
        );
        if (!mappingRes.ok) {
          const data = await mappingRes.json().catch(() => null);
          setError(data?.detail || "Erro ao atualizar colunas da base.");
          return;
        }
        onColumnMappingUpdated(columnMapping);
      }

      const payload = {
        lead_base_id: leadBase.id,
        id_cliente: formValues.id_cliente?.trim() || null,
        nome_cliente: nome,
        cpf_cliente: formValues.cpf_cliente?.trim() || null,
        email_cliente: formValues.email_cliente?.trim() || null,
        telefone_1: formValues.telefone_1?.trim() || null,
        telefone_2: formValues.telefone_2?.trim() || null,
        telefone_3: formValues.telefone_3?.trim() || null,
        aux_values: Object.fromEntries(
          Object.entries(auxValues).filter(([, value]) => value.trim()),
        ),
      };

      const res = await apiFetch("/api/v1/leads/", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Erro ao criar lead.");
        return;
      }

      setFormValues({});
      setAuxValues({});
      onSuccess();
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="glass-card p-6">
      <h2 className="mb-5 text-lg font-semibold text-foreground">Novo lead manual</h2>

      {error && <Alert>{error}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {FIXED_LEAD_COLUMNS.map((column) => (
            <div key={column.key}>
              <label
                htmlFor={column.key}
                className="mb-2 block text-sm font-medium text-foreground"
              >
                {column.label}
                {column.key === "nome_cliente" && " *"}
              </label>
              <input
                id={column.key}
                type={column.key === "email_cliente" ? "email" : "text"}
                required={column.key === "nome_cliente"}
                value={formValues[column.key] ?? ""}
                onChange={(event) => updateFixedField(column.key, event.target.value)}
                className="input-field"
              />
            </div>
          ))}
        </div>

        {auxKeys.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {auxKeys.map((auxKey) => (
              <div key={auxKey}>
                <label
                  htmlFor={auxKey}
                  className="mb-2 block text-sm font-medium text-foreground"
                >
                  {columnMapping[auxKey]}
                </label>
                <input
                  id={auxKey}
                  type="text"
                  value={auxValues[auxKey] ?? ""}
                  onChange={(event) => updateAuxField(auxKey, event.target.value)}
                  className="input-field"
                />
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setShowColumnModal(true)}
            disabled={auxKeys.length >= 45}
          >
            Adicionar coluna personalizada
          </button>
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? "Salvando..." : "Salvar lead"}
          </button>
        </div>
      </form>

      <CustomColumnModal
        open={showColumnModal}
        onClose={() => setShowColumnModal(false)}
        onConfirm={handleAddColumn}
        existingCount={auxKeys.length}
      />
    </div>
  );
}
