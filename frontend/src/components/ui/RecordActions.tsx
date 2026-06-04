"use client";

import { Eye, Pencil, Play, Trash2 } from "lucide-react";
import type { RecordActions as Actions } from "@/lib/protection";

interface RecordActionsProps {
  actions: Actions;
  onView?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onStart?: () => void;
  startLoading?: boolean;
  deleteLoading?: boolean;
}

const iconBtn =
  "inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-40";

export function RecordActionsBar({
  actions,
  onView,
  onEdit,
  onDelete,
  onStart,
  startLoading = false,
  deleteLoading = false,
}: RecordActionsProps) {
  return (
    <div className="flex items-center justify-end gap-1">
      {actions.canView && onView && (
        <button
          type="button"
          className={iconBtn}
          title="Visualizar"
          aria-label="Visualizar"
          onClick={onView}
        >
          <Eye className="h-4 w-4" />
        </button>
      )}
      {actions.canEdit && onEdit && (
        <button
          type="button"
          className={iconBtn}
          title="Editar"
          aria-label="Editar"
          onClick={onEdit}
        >
          <Pencil className="h-4 w-4" />
        </button>
      )}
      {onStart && actions.canEdit && (
        <button
          type="button"
          className={iconBtn}
          title="Iniciar campanha"
          aria-label="Iniciar campanha"
          disabled={startLoading}
          onClick={onStart}
        >
          <Play className="h-4 w-4" />
        </button>
      )}
      {actions.canDelete && onDelete && (
        <button
          type="button"
          className={iconBtn}
          title="Excluir"
          aria-label="Excluir"
          disabled={deleteLoading}
          onClick={onDelete}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
