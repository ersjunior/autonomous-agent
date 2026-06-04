"use client";

import { FormEvent, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { MAX_AUX_COLUMNS } from "@/lib/types/leads";

interface CustomColumnModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (columnName: string) => void;
  existingCount: number;
}

export function CustomColumnModal({
  open,
  onClose,
  onConfirm,
  existingCount,
}: CustomColumnModalProps) {
  const [columnName, setColumnName] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = columnName.trim();
    if (!trimmed) {
      return;
    }
    onConfirm(trimmed);
    setColumnName("");
    onClose();
  }

  return (
    <Modal open={open} title="Adicionar coluna personalizada" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Defina o nome da coluna extra. Máximo de {MAX_AUX_COLUMNS} colunas ({existingCount}/
          {MAX_AUX_COLUMNS} em uso).
        </p>
        <div>
          <label htmlFor="columnName" className="mb-2 block text-sm font-medium text-foreground">
            Nome da coluna
          </label>
          <input
            id="columnName"
            type="text"
            required
            value={columnName}
            onChange={(event) => setColumnName(event.target.value)}
            className="input-field"
            placeholder="Ex: Placa do Veículo"
          />
        </div>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancelar
          </button>
          <button type="submit" className="btn-primary" disabled={existingCount >= MAX_AUX_COLUMNS}>
            Adicionar
          </button>
        </div>
      </form>
    </Modal>
  );
}
