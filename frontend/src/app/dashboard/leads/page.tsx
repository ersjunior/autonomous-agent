"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { ImportCsvWizard } from "@/components/leads/ImportCsvWizard";
import { LeadsTable } from "@/components/leads/LeadsTable";
import { ManualLeadForm } from "@/components/leads/ManualLeadForm";
import { deleteLeadBase } from "@/lib/api-entities";
import { apiDownload, apiFetch } from "@/lib/api";
import { canDeleteLeadBase, isImportLeadBase } from "@/lib/protection";
import type {
  DevolutivaFile,
  LeadBase,
  LeadBaseListResponse,
  LeadListResponse,
} from "@/lib/types/leads";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { SystemBadge } from "@/components/ui/SystemBadge";

const PAGE_SIZE = 20;

export default function LeadsPage() {
  const [leadBases, setLeadBases] = useState<LeadBase[]>([]);
  const [selectedBaseId, setSelectedBaseId] = useState("");
  const [selectedBase, setSelectedBase] = useState<LeadBase | null>(null);
  const [leads, setLeads] = useState<LeadListResponse["items"]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loadingBases, setLoadingBases] = useState(true);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [showManualForm, setShowManualForm] = useState(false);
  const [error, setError] = useState("");
  const [devolutivas, setDevolutivas] = useState<DevolutivaFile[]>([]);
  const [loadingDevolutivas, setLoadingDevolutivas] = useState(false);
  const [downloadingDevolutiva, setDownloadingDevolutiva] = useState(false);
  const [deleteBaseOpen, setDeleteBaseOpen] = useState(false);
  const [deletingBase, setDeletingBase] = useState(false);
  const [success, setSuccess] = useState("");

  const loadLeadBases = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setLoadingBases(true);
    setError("");
    try {
      const res = await apiFetch("/api/v1/lead-bases/?skip=0&limit=200");
      if (!res.ok) {
        setError("Erro ao carregar bases de leads.");
        return;
      }

      const data: LeadBaseListResponse = await res.json();
      setLeadBases(data.items);

      if (data.items.length === 0) {
        setSelectedBaseId("");
        setSelectedBase(null);
        return;
      }

      setSelectedBaseId((current) => {
        const stillExists = data.items.some((base) => base.id === current);
        return stillExists ? current : data.items[0].id;
      });
    } catch {
      setError("Erro de conexão ao carregar bases.");
    } finally {
      setLoadingBases(false);
    }
  }, []);

  const loadLeads = useCallback(
    async (baseId: string, pageSkip: number) => {
      if (!baseId) {
        setLeads([]);
        setTotal(0);
        return;
      }

      setLoadingLeads(true);
      try {
        const res = await apiFetch(
          `/api/v1/lead-bases/${baseId}/leads?skip=${pageSkip}&limit=${PAGE_SIZE}`,
        );
        if (!res.ok) {
          setError("Erro ao carregar leads da base.");
          return;
        }

        const data: LeadListResponse = await res.json();
        setLeads(data.items);
        setTotal(data.total);
        setSkip(data.skip);
      } catch {
        setError("Erro de conexão ao carregar leads.");
      } finally {
        setLoadingLeads(false);
      }
    },
    [],
  );

  const loadDevolutivas = useCallback(async (baseId: string) => {
    if (!baseId) {
      setDevolutivas([]);
      return;
    }

    setLoadingDevolutivas(true);
    try {
      const res = await apiFetch(`/api/v1/lead-bases/${baseId}/devolutivas`);
      if (!res.ok) {
        setDevolutivas([]);
        return;
      }

      const data: DevolutivaFile[] = await res.json();
      setDevolutivas(data);
    } catch {
      setDevolutivas([]);
    } finally {
      setLoadingDevolutivas(false);
    }
  }, []);

  async function handleDownloadDevolutivaNow() {
    if (!selectedBaseId) {
      return;
    }

    setDownloadingDevolutiva(true);
    setError("");
    try {
      await apiDownload(`/api/v1/lead-bases/${selectedBaseId}/devolutiva`);
    } catch {
      setError("Erro ao baixar devolutiva.");
    } finally {
      setDownloadingDevolutiva(false);
    }
  }

  async function handleDownloadHistoricalDevolutiva(data: string) {
    if (!selectedBaseId) {
      return;
    }

    setError("");
    try {
      await apiDownload(`/api/v1/lead-bases/${selectedBaseId}/devolutivas/${data}`);
    } catch {
      setError("Erro ao baixar devolutiva histórica.");
    }
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  useEffect(() => {
    loadLeadBases();
  }, [loadLeadBases]);

  useEffect(() => {
    const base = leadBases.find((item) => item.id === selectedBaseId) ?? null;
    setSelectedBase(base);
    setSkip(0);
    if (base) {
      loadLeads(base.id, 0);
      loadDevolutivas(base.id);
    } else {
      setLeads([]);
      setTotal(0);
      setDevolutivas([]);
    }
  }, [selectedBaseId, leadBases, loadLeads, loadDevolutivas]);

  function handleImportSuccess(leadBaseId: string) {
    setSelectedBaseId(leadBaseId);
    loadLeadBases();
  }

  function handleLeadCreated() {
    if (selectedBaseId) {
      loadLeads(selectedBaseId, skip);
      loadLeadBases();
    }
    setShowManualForm(false);
  }

  async function confirmDeleteBase() {
    if (!selectedBaseId) {
      return;
    }
    setDeletingBase(true);
    setError("");
    try {
      await deleteLeadBase(selectedBaseId);
      setSuccess("Base de leads excluída com todos os seus leads.");
      setDeleteBaseOpen(false);
      await loadLeadBases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir base.");
    } finally {
      setDeletingBase(false);
    }
  }

  const baseIsImport = isImportLeadBase(selectedBase?.source);
  const canDeleteBase = canDeleteLeadBase(selectedBase);

  function handleColumnMappingUpdated(mapping: Record<string, string>) {
    setLeadBases((current) =>
      current.map((base) =>
        base.id === selectedBaseId ? { ...base, column_mapping: mapping } : base,
      ),
    );
    setSelectedBase((current) =>
      current ? { ...current, column_mapping: mapping } : current,
    );
  }

  return (
    <>
      <PageHeader
        title="Leads"
        description="Gerencie bases de contatos, importações CSV e leads manuais."
        actions={
          <>
            <button type="button" onClick={() => setShowWizard(true)} className="btn-secondary">
              Importar CSV
            </button>
            <button
              type="button"
              onClick={() => setShowManualForm((current) => !current)}
              className="btn-primary"
              disabled={!selectedBase || baseIsImport}
              title={
                baseIsImport
                  ? "Bases importadas não permitem inclusão manual de leads"
                  : undefined
              }
            >
              {showManualForm ? "Cancelar" : "Novo lead"}
            </button>
          </>
        }
      />

      {error && <Alert>{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      <div className="glass-card mb-6 p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <label htmlFor="leadBase" className="text-sm font-medium text-foreground">
            Base de leads
          </label>
          {selectedBase && canDeleteBase && (
            <button
              type="button"
              className="btn-secondary text-sm text-destructive"
              onClick={() => setDeleteBaseOpen(true)}
            >
              Excluir base
            </button>
          )}
        </div>
        {loadingBases ? (
          <p className="text-sm text-muted-foreground">Carregando bases...</p>
        ) : leadBases.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nenhuma base cadastrada. Importe um CSV para começar.
          </p>
        ) : (
          <select
            id="leadBase"
            value={selectedBaseId}
            onChange={(event) => setSelectedBaseId(event.target.value)}
            className="input-field max-w-xl"
          >
            {leadBases.map((base) => (
              <option key={base.id} value={base.id}>
                {base.data_recebimento} — {base.leads_count} lead(s) —{" "}
                {base.channel_types.join(", ")}
              </option>
            ))}
          </select>
        )}

        {selectedBase && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {selectedBase.is_system && <SystemBadge />}
            <Badge variant={baseIsImport ? "warning" : "success"}>
              {baseIsImport
                ? "Importada (somente leitura)"
                : "Manual (edição permitida)"}
            </Badge>
          </div>
        )}

        {selectedBase && (
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <div className="grid flex-1 gap-2 text-sm text-muted-foreground md:grid-cols-3">
              <span>Recebimento: {selectedBase.data_recebimento}</span>
              <span>Início: {selectedBase.data_inicio || "—"}</span>
              <span>Fim: {selectedBase.data_fim || "—"}</span>
            </div>
            <button
              type="button"
              onClick={handleDownloadDevolutivaNow}
              className="btn-secondary shrink-0"
              disabled={downloadingDevolutiva}
            >
              {downloadingDevolutiva ? "Gerando..." : "Baixar devolutiva (agora)"}
            </button>
          </div>
        )}
      </div>

      {selectedBase && (
        <div className="glass-card mb-6 p-5">
          <h2 className="mb-3 text-sm font-medium text-foreground">Devolutivas anteriores</h2>
          {loadingDevolutivas ? (
            <p className="text-sm text-muted-foreground">Carregando devolutivas...</p>
          ) : devolutivas.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nenhuma devolutiva histórica disponível para esta base.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {devolutivas.map((file) => (
                <li
                  key={file.data}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <div className="text-sm">
                    <span className="font-medium text-foreground">{file.data}</span>
                    <span className="ml-2 text-muted-foreground">
                      {file.filename} · {formatFileSize(file.size_bytes)}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDownloadHistoricalDevolutiva(file.data)}
                    className="btn-secondary text-sm"
                  >
                    Baixar
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showManualForm && selectedBase && (
        <div className="mb-8">
          <ManualLeadForm
            leadBase={selectedBase}
            onSuccess={handleLeadCreated}
            onColumnMappingUpdated={handleColumnMappingUpdated}
          />
        </div>
      )}

      <LeadsTable
        selectedBase={selectedBase}
        columnMapping={selectedBase?.column_mapping ?? {}}
        leads={leads}
        total={total}
        skip={skip}
        limit={PAGE_SIZE}
        loading={loadingLeads}
        onPageChange={(nextSkip) => {
          if (selectedBaseId) {
            loadLeads(selectedBaseId, nextSkip);
          }
        }}
        onRefresh={() => {
          if (selectedBaseId) {
            loadLeads(selectedBaseId, skip);
          }
        }}
        onError={setError}
      />

      <ConfirmDeleteModal
        open={deleteBaseOpen}
        title="Excluir base de leads"
        message={`Tem certeza? Todos os ${selectedBase?.leads_count ?? 0} lead(s) desta base serão apagados permanentemente. Esta ação não pode ser desfeita.`}
        confirmLabel="Excluir base inteira"
        loading={deletingBase}
        onClose={() => setDeleteBaseOpen(false)}
        onConfirm={confirmDeleteBase}
      />

      <ImportCsvWizard
        open={showWizard}
        onClose={() => setShowWizard(false)}
        onSuccess={handleImportSuccess}
      />
    </>
  );
}
