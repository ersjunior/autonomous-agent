"use client";

import { Modal } from "@/components/ui/Modal";

interface ConfirmDeleteModalProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  loading?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function ConfirmDeleteModal({
  open,
  title,
  message,
  confirmLabel = "Excluir",
  loading = false,
  onClose,
  onConfirm,
}: ConfirmDeleteModalProps) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <p className="mb-6 text-sm text-muted-foreground">{message}</p>
      <div className="flex justify-end gap-3">
        <button type="button" onClick={onClose} className="btn-secondary" disabled={loading}>
          Cancelar
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={loading}
          className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground transition hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Excluindo..." : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
