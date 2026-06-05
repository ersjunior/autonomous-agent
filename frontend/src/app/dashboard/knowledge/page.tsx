"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createManualKnowledge,
  deleteKnowledgeDocument,
  fetchKnowledgeDocuments,
} from "@/lib/api-entities";
import { formatApiError, uploadKnowledgeDocument } from "@/lib/api";
import type { KBDocument, KBDocumentStatus } from "@/lib/types/knowledge";
import { actionsFor } from "@/lib/protection";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

const STATUS_LABELS: Record<KBDocumentStatus, string> = {
  PROCESSING: "Processando",
  READY: "Pronto",
  ERROR: "Erro",
};

const STATUS_VARIANTS: Record<KBDocumentStatus, "warning" | "success" | "muted"> = {
  PROCESSING: "warning",
  READY: "success",
  ERROR: "muted",
};

type AddMode = "upload" | "manual" | null;

function KBProgressCell({ doc }: { doc: KBDocument }) {
  if (doc.status !== "PROCESSING") {
    if (doc.status === "READY") {
      return <span className="text-muted-foreground">{doc.chunk_count} chunks</span>;
    }
    return <span className="text-muted-foreground">—</span>;
  }

  const total = doc.total_chunks_estimated ?? 0;
  const done = doc.chunks_processed ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null;

  return (
    <div className="min-w-[140px] space-y-1">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span
          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-500 border-t-transparent"
          aria-hidden
        />
        {total > 0 ? (
          <span>
            {done}/{total} chunks ({pct}%)
          </span>
        ) : (
          <span>Extraindo texto…</span>
        )}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-amber-500 transition-all duration-500 ease-out"
          style={{ width: pct !== null ? `${pct}%` : "30%" }}
        />
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KBDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [title, setTitle] = useState("");
  const [manualContent, setManualContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<KBDocument | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [viewDoc, setViewDoc] = useState<KBDocument | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await fetchKnowledgeDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar documentos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === "PROCESSING");
    if (!hasProcessing) {
      return;
    }
    const timer = setInterval(() => {
      void loadDocuments();
    }, 5000);
    return () => clearInterval(timer);
  }, [documents, loadDocuments]);

  function openAdd(mode: AddMode) {
    setAddMode(mode);
    setTitle("");
    setManualContent("");
    setFile(null);
    setError("");
    setSuccess("");
  }

  function closeAdd() {
    setAddMode(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setSubmitting(true);

    try {
      if (addMode === "manual") {
        await createManualKnowledge({ title, content: manualContent });
        setSuccess("Documento manual enfileirado para processamento.");
      } else if (addMode === "upload") {
        if (!file) {
          setError("Selecione um arquivo PDF, DOCX ou TXT.");
          setSubmitting(false);
          return;
        }
        const res = await uploadKnowledgeDocument(file, title || undefined);
        if (!res.ok) {
          throw new Error(await formatApiError(res, "Erro no upload"));
        }
        setSuccess("Upload enfileirado para processamento.");
      }
      closeAdd();
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao adicionar documento.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteKnowledgeDocument(deleteTarget.id);
      setSuccess("Documento excluído.");
      setDeleteTarget(null);
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir documento.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Conhecimento"
        description="Base documental da empresa — FAQs, políticas e materiais para o agente (ingestão assíncrona)."
        actions={
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={() => void loadDocuments()}>
              Atualizar
            </button>
            <button type="button" className="btn-primary" onClick={() => openAdd("upload")}>
              Upload de arquivo
            </button>
            <button type="button" className="btn-secondary" onClick={() => openAdd("manual")}>
              Texto manual
            </button>
          </div>
        }
      />

      {error && <Alert variant="error">{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      {loading ? (
        <div className="glass-card p-8 text-center text-muted-foreground">Carregando...</div>
      ) : documents.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhum documento na base. Faça upload ou cole um texto manual.
        </div>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-border/60 text-muted-foreground">
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-4 py-3 font-medium">Tipo</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Progresso</th>
                <th className="px-4 py-3 font-medium">Chunks</th>
                <th className="px-4 py-3 font-medium">Criado</th>
                <th className="px-4 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => {
                const actions = actionsFor(doc);
                const status = doc.status as KBDocumentStatus;
                return (
                  <tr key={doc.id} className="border-b border-border/40 last:border-0">
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-foreground">{doc.title}</span>
                        {doc.is_system && <SystemBadge />}
                      </div>
                      {doc.filename && (
                        <p className="text-xs text-muted-foreground">{doc.filename}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {doc.source_type === "UPLOAD" ? "Upload" : "Manual"}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={STATUS_VARIANTS[status] ?? "muted"}>
                        {status === "PROCESSING" && (
                          <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-amber-400" />
                        )}
                        {STATUS_LABELS[status] ?? doc.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <KBProgressCell doc={doc} />
                    </td>
                    <td className="px-4 py-3">{doc.chunk_count}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {new Date(doc.created_at).toLocaleString("pt-BR")}
                    </td>
                    <td className="px-4 py-3">
                      <RecordActionsBar
                        actions={actions}
                        onView={() => setViewDoc(doc)}
                        onDelete={() => setDeleteTarget(doc)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={addMode !== null}
        onClose={closeAdd}
        title={addMode === "manual" ? "Adicionar texto manual" : "Upload de documento"}
      >
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm text-muted-foreground">Título</label>
            <input
              className="input-field w-full"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required={addMode === "manual"}
              placeholder={addMode === "upload" ? "Opcional — usa nome do arquivo" : "Ex.: FAQ produtos"}
            />
          </div>
          {addMode === "upload" ? (
            <div>
              <label className="mb-1 block text-sm text-muted-foreground">Arquivo (PDF, DOCX, TXT)</label>
              <input
                type="file"
                accept=".pdf,.docx,.txt,application/pdf,text/plain"
                className="w-full text-sm"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          ) : (
            <div>
              <label className="mb-1 block text-sm text-muted-foreground">Conteúdo</label>
              <textarea
                className="input-field min-h-[200px] w-full"
                value={manualContent}
                onChange={(e) => setManualContent(e.target.value)}
                required
                placeholder="Cole políticas, FAQ ou material de referência..."
              />
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={closeAdd}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? "Enviando..." : "Adicionar"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={viewDoc !== null} onClose={() => setViewDoc(null)} title="Detalhe do documento">
        {viewDoc && (
          <div className="space-y-3 text-sm">
            <p>
              <span className="text-muted-foreground">Status:</span>{" "}
              {STATUS_LABELS[viewDoc.status as KBDocumentStatus] ?? viewDoc.status}
            </p>
            <p>
              <span className="text-muted-foreground">Chunks:</span> {viewDoc.chunk_count}
            </p>
            {viewDoc.status === "PROCESSING" && (
              <p>
                <span className="text-muted-foreground">Progresso:</span>{" "}
                {viewDoc.total_chunks_estimated > 0
                  ? `${viewDoc.chunks_processed}/${viewDoc.total_chunks_estimated}`
                  : "Extraindo texto…"}
              </p>
            )}
            <p>
              <span className="text-muted-foreground">Tipo:</span>{" "}
              {viewDoc.source_type === "UPLOAD" ? "Upload" : "Manual"}
            </p>
            {viewDoc.error_message && (
              <Alert variant="error">{viewDoc.error_message}</Alert>
            )}
          </div>
        )}
      </Modal>

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir documento"
        message={`Remover "${deleteTarget?.title}" da base? Chunks e arquivo serão apagados.`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
