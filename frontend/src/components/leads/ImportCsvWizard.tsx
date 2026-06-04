"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Modal } from "@/components/ui/Modal";
import { apiFetch, apiUpload } from "@/lib/api";
import {
  analyzeCsv,
  buildPreviewRows,
  type CsvMappingResult,
} from "@/lib/csv";
import type { Campaign } from "@/lib/types/campaigns";
import { FIXED_LEAD_COLUMNS, sortAuxKeys } from "@/lib/types/leads";

interface ImportCsvWizardProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (leadBaseId: string) => void;
}

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  voice: "Voz",
  video: "Vídeo",
};

export function ImportCsvWizard({ open, onClose, onSuccess }: ImportCsvWizardProps) {
  const [step, setStep] = useState(1);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [dataRecebimento, setDataRecebimento] = useState("");
  const [dataInicio, setDataInicio] = useState("");
  const [dataFim, setDataFim] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvAnalysis, setCsvAnalysis] = useState<CsvMappingResult | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [loadingCampaigns, setLoadingCampaigns] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      return;
    }

    async function loadCampaigns() {
      setLoadingCampaigns(true);
      setError("");
      try {
        const res = await apiFetch("/api/v1/campaigns/");
        if (!res.ok) {
          setError("Erro ao carregar campanhas.");
          return;
        }
        const data: Campaign[] = await res.json();
        setCampaigns(data);
        if (data.length > 0) {
          setSelectedCampaignId(data[0].id);
          setAvailableChannels(data[0].channel_types);
          setSelectedChannels(data[0].channel_types.slice(0, 1));
        }
      } catch {
        setError("Erro de conexão ao carregar campanhas.");
      } finally {
        setLoadingCampaigns(false);
      }
    }

    loadCampaigns();
  }, [open]);

  useEffect(() => {
    const campaign = campaigns.find((item) => item.id === selectedCampaignId);
    if (!campaign) {
      return;
    }
    setAvailableChannels(campaign.channel_types);
    setSelectedChannels((current) =>
      current.filter((channel) => campaign.channel_types.includes(channel)),
    );
  }, [selectedCampaignId, campaigns]);

  const previewLeads = useMemo(() => {
    if (!csvAnalysis) {
      return [];
    }
    return buildPreviewRows(csvAnalysis.rows, csvAnalysis.indexToField).slice(0, 10);
  }, [csvAnalysis]);

  function resetWizard() {
    setStep(1);
    setSelectedCampaignId(campaigns[0]?.id ?? "");
    setAvailableChannels(campaigns[0]?.channel_types ?? []);
    setSelectedChannels(campaigns[0]?.channel_types.slice(0, 1) ?? []);
    setDataRecebimento("");
    setDataInicio("");
    setDataFim("");
    setCsvFile(null);
    setCsvAnalysis(null);
    setColumnMapping({});
    setError("");
  }

  function handleClose() {
    resetWizard();
    onClose();
  }

  function toggleChannel(channel: string) {
    setSelectedChannels((current) =>
      current.includes(channel)
        ? current.filter((item) => item !== channel)
        : [...current, channel],
    );
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    setCsvFile(file);
    const content = await file.text();
    const analysis = analyzeCsv(content);
    setCsvAnalysis(analysis);
    setColumnMapping(analysis.columnMapping);
    setError("");
  }

  async function goToStep3() {
    if (!dataRecebimento) {
      setError("Informe a data de recebimento da base.");
      return;
    }
    if (selectedChannels.length === 0) {
      setError("Selecione ao menos um canal.");
      return;
    }
    if (!csvFile || !csvAnalysis) {
      setError("Selecione um arquivo CSV válido.");
      return;
    }
    if (csvAnalysis.rows.length === 0) {
      setError("O CSV não possui linhas de dados.");
      return;
    }

    setError("");
    setStep(3);
  }

  function updateAuxLabel(auxKey: string, label: string) {
    setColumnMapping((current) => ({ ...current, [auxKey]: label }));
  }

  async function handleImport() {
    if (!csvFile || !selectedCampaignId) {
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      const formData = new FormData();
      formData.append("campaign_id", selectedCampaignId);
      selectedChannels.forEach((channel) => formData.append("channel_types", channel));
      formData.append("data_recebimento", dataRecebimento);
      if (dataInicio) {
        formData.append("data_inicio", dataInicio);
      }
      if (dataFim) {
        formData.append("data_fim", dataFim);
      }
      formData.append("file", csvFile);

      const res = await apiUpload("/api/v1/lead-bases/import", formData);
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(typeof data?.detail === "string" ? data.detail : "Erro ao importar CSV.");
        return;
      }

      const leadBase = await res.json();
      const mappingChanged =
        JSON.stringify(columnMapping) !== JSON.stringify(leadBase.column_mapping ?? {});

      if (mappingChanged) {
        await apiFetch(`/api/v1/lead-bases/${leadBase.id}/column-mapping`, {
          method: "PATCH",
          body: JSON.stringify({ column_mapping: columnMapping }),
        });
      }

      onSuccess(leadBase.id);
      handleClose();
    } catch {
      setError("Erro de conexão ao importar CSV.");
    } finally {
      setSubmitting(false);
    }
  }

  const auxKeys = sortAuxKeys(Object.keys(columnMapping));

  return (
    <Modal open={open} title="Importar base de leads (CSV)" onClose={handleClose} wide>
      <div className="mb-6 flex items-center gap-2 text-sm">
        {[1, 2, 3].map((wizardStep) => (
          <div
            key={wizardStep}
            className={`rounded-full px-3 py-1 ${
              step === wizardStep
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground"
            }`}
          >
            Passo {wizardStep}
          </div>
        ))}
      </div>

      {error && <Alert>{error}</Alert>}

      {step === 1 && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Selecione a campanha. Os canais disponíveis serão carregados automaticamente.
          </p>
          {loadingCampaigns ? (
            <p className="text-muted-foreground">Carregando campanhas...</p>
          ) : campaigns.length === 0 ? (
            <Alert variant="warning">Cadastre uma campanha com canais antes de importar.</Alert>
          ) : (
            <div>
              <label htmlFor="campaign" className="mb-2 block text-sm font-medium text-foreground">
                Campanha
              </label>
              <select
                id="campaign"
                value={selectedCampaignId}
                onChange={(event) => setSelectedCampaignId(event.target.value)}
                className="input-field"
              >
                {campaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {availableChannels.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Canais da campanha</p>
              <div className="flex flex-wrap gap-2">
                {availableChannels.map((channel) => (
                  <span
                    key={channel}
                    className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground"
                  >
                    {CHANNEL_LABELS[channel] ?? channel}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="button"
              className="btn-primary"
              disabled={!selectedCampaignId || campaigns.length === 0}
              onClick={() => setStep(2)}
            >
              Próximo
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-sm font-medium text-foreground">Canais para acionar a base</p>
            <div className="flex flex-wrap gap-3">
              {availableChannels.map((channel) => (
                <label key={channel} className="flex items-center gap-2 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={selectedChannels.includes(channel)}
                    onChange={() => toggleChannel(channel)}
                  />
                  {CHANNEL_LABELS[channel] ?? channel}
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label htmlFor="dataRecebimento" className="mb-2 block text-sm font-medium text-foreground">
                Data recebimento *
              </label>
              <input
                id="dataRecebimento"
                type="date"
                required
                value={dataRecebimento}
                onChange={(event) => setDataRecebimento(event.target.value)}
                className="input-field"
              />
            </div>
            <div>
              <label htmlFor="dataInicio" className="mb-2 block text-sm font-medium text-foreground">
                Data início
              </label>
              <input
                id="dataInicio"
                type="date"
                value={dataInicio}
                onChange={(event) => setDataInicio(event.target.value)}
                className="input-field"
              />
            </div>
            <div>
              <label htmlFor="dataFim" className="mb-2 block text-sm font-medium text-foreground">
                Data fim
              </label>
              <input
                id="dataFim"
                type="date"
                value={dataFim}
                onChange={(event) => setDataFim(event.target.value)}
                className="input-field"
              />
            </div>
          </div>

          <div>
            <label htmlFor="csvFile" className="mb-2 block text-sm font-medium text-foreground">
              Arquivo CSV
            </label>
            <input
              id="csvFile"
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="input-field"
            />
            {csvFile && (
              <p className="mt-2 text-sm text-muted-foreground">
                {csvFile.name} — {csvAnalysis?.rows.length ?? 0} linha(s) detectada(s)
              </p>
            )}
          </div>

          <div className="flex justify-between">
            <button type="button" className="btn-secondary" onClick={() => setStep(1)}>
              Voltar
            </button>
            <button type="button" className="btn-primary" onClick={goToStep3}>
              Próximo
            </button>
          </div>
        </div>
      )}

      {step === 3 && csvAnalysis && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Revise o mapeamento detectado. Você pode renomear as colunas auxiliares antes de
            confirmar a importação.
          </p>

          {auxKeys.length > 0 && (
            <div className="grid gap-3 md:grid-cols-2">
              {auxKeys.map((auxKey) => (
                <div key={auxKey}>
                  <label className="mb-2 block text-sm font-medium text-foreground">
                    {auxKey} → rótulo exibido
                  </label>
                  <input
                    type="text"
                    value={columnMapping[auxKey] ?? ""}
                    onChange={(event) => updateAuxLabel(auxKey, event.target.value)}
                    className="input-field"
                  />
                </div>
              ))}
            </div>
          )}

          <div className="glass-card overflow-x-auto p-2">
            <table className="min-w-full divide-y divide-border">
              <thead className="bg-muted/50">
                <tr>
                  {FIXED_LEAD_COLUMNS.map((column) => (
                    <th
                      key={column.key}
                      className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium uppercase text-muted-foreground"
                    >
                      {column.label}
                    </th>
                  ))}
                  {auxKeys.map((auxKey) => (
                    <th
                      key={auxKey}
                      className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium uppercase text-muted-foreground"
                    >
                      {columnMapping[auxKey]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {previewLeads.map((row, index) => (
                  <tr key={index}>
                    {FIXED_LEAD_COLUMNS.map((column) => (
                      <td key={column.key} className="whitespace-nowrap px-3 py-2 text-sm">
                        {(row[column.key as keyof typeof row] as string | undefined) || "—"}
                      </td>
                    ))}
                    {auxKeys.map((auxKey) => (
                      <td key={auxKey} className="whitespace-nowrap px-3 py-2 text-sm">
                        {row.aux_values[auxKey] || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            Pré-visualização das primeiras {previewLeads.length} linhas de {csvAnalysis.rows.length}{" "}
            no total.
          </p>

          <div className="flex justify-between">
            <button type="button" className="btn-secondary" onClick={() => setStep(2)}>
              Voltar
            </button>
            <button type="button" className="btn-primary" disabled={submitting} onClick={handleImport}>
              {submitting ? "Importando..." : "Importar"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
