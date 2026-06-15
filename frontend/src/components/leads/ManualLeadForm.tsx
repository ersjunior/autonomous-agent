"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { SystemBadge } from "@/components/ui/SystemBadge";
import { apiFetch } from "@/lib/api";
import { fetchCampaigns } from "@/lib/api-entities";
import type { Campaign } from "@/lib/types/campaigns";
import {
  FIXED_LEAD_COLUMNS,
  type LeadBase,
  nextAuxKey,
  sortAuxKeys,
} from "@/lib/types/leads";
import { CustomColumnModal } from "./CustomColumnModal";

const NEW_BASE_VALUE = "__new__";

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  voice: "Voz",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function isManualBase(base: LeadBase): boolean {
  return base.source !== "IMPORT";
}

function formatApiDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") {
    return null;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : ""))
      .filter(Boolean)
      .join(", ");
  }
  return null;
}

interface ManualLeadFormProps {
  leadBases: LeadBase[];
  /** Base manual já selecionada na página — pré-preenche campanha/base. */
  initialManualBase?: LeadBase | null;
  onSuccess: (leadBaseId: string) => void;
  onCancel?: () => void;
  onBasesChanged?: () => void | Promise<void>;
  onColumnMappingUpdated?: (baseId: string, mapping: Record<string, string>) => void;
}

export function ManualLeadForm({
  leadBases,
  initialManualBase,
  onSuccess,
  onCancel,
  onBasesChanged,
  onColumnMappingUpdated,
}: ManualLeadFormProps) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loadingCampaigns, setLoadingCampaigns] = useState(true);
  const [campaignId, setCampaignId] = useState("");
  const [baseSelection, setBaseSelection] = useState<string>(NEW_BASE_VALUE);

  const [dataRecebimento, setDataRecebimento] = useState(todayIso());
  const [dataInicio, setDataInicio] = useState("");
  const [dataFim, setDataFim] = useState("");
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [auxValues, setAuxValues] = useState<Record<string, string>>({});
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [showColumnModal, setShowColumnModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const selectedCampaign = campaigns.find((c) => c.id === campaignId) ?? null;

  const manualBasesForCampaign = useMemo(
    () =>
      leadBases.filter(
        (base) => base.campaign_id === campaignId && isManualBase(base),
      ),
    [leadBases, campaignId],
  );

  const isNewBase = baseSelection === NEW_BASE_VALUE;
  const selectedExistingBase =
    !isNewBase ? manualBasesForCampaign.find((b) => b.id === baseSelection) ?? null : null;

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoadingCampaigns(true);
      setError("");
      try {
        const data = await fetchCampaigns();
        if (cancelled) {
          return;
        }
        setCampaigns(data);
        if (data.length === 0) {
          return;
        }

        const initialCampaign =
          initialManualBase?.campaign_id &&
          data.some((c) => c.id === initialManualBase.campaign_id)
            ? initialManualBase.campaign_id
            : data[0].id;

        setCampaignId(initialCampaign);

        if (initialManualBase && initialManualBase.campaign_id === initialCampaign) {
          setBaseSelection(initialManualBase.id);
          setColumnMapping(initialManualBase.column_mapping ?? {});
        } else {
          setBaseSelection(NEW_BASE_VALUE);
          setColumnMapping({});
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erro ao carregar campanhas.");
        }
      } finally {
        if (!cancelled) {
          setLoadingCampaigns(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [initialManualBase]);

  useEffect(() => {
    if (!selectedCampaign) {
      return;
    }
    setSelectedChannels((current) => {
      const valid = current.filter((ch) => selectedCampaign.channel_types.includes(ch));
      if (valid.length > 0) {
        return valid;
      }
      return [...selectedCampaign.channel_types];
    });
  }, [selectedCampaign]);

  useEffect(() => {
    if (isNewBase) {
      return;
    }
    if (selectedExistingBase) {
      setColumnMapping(selectedExistingBase.column_mapping ?? {});
      setAuxValues({});
      return;
    }
    if (manualBasesForCampaign.length > 0 && baseSelection !== NEW_BASE_VALUE) {
      const stillValid = manualBasesForCampaign.some((b) => b.id === baseSelection);
      if (!stillValid) {
        setBaseSelection(manualBasesForCampaign[0].id);
      }
    }
  }, [baseSelection, isNewBase, selectedExistingBase, manualBasesForCampaign]);

  function handleCampaignChange(nextCampaignId: string) {
    setCampaignId(nextCampaignId);
    const bases = leadBases.filter(
      (base) => base.campaign_id === nextCampaignId && isManualBase(base),
    );
    if (bases.length > 0) {
      setBaseSelection(bases[0].id);
      setColumnMapping(bases[0].column_mapping ?? {});
    } else {
      setBaseSelection(NEW_BASE_VALUE);
      setColumnMapping({});
    }
    setDataRecebimento(todayIso());
    setDataInicio("");
    setDataFim("");
    setFormValues({});
    setAuxValues({});
    setError("");
  }

  function toggleChannel(channel: string) {
    setSelectedChannels((current) =>
      current.includes(channel)
        ? current.filter((item) => item !== channel)
        : [...current, channel],
    );
  }

  function updateFixedField(key: string, value: string) {
    setFormValues((current) => ({ ...current, [key]: value }));
  }

  function updateAuxField(key: string, value: string) {
    setAuxValues((current) => ({ ...current, [key]: value }));
  }

  function handleAddColumn(columnName: string) {
    const auxKey = nextAuxKey(columnMapping);
    if (!auxKey) {
      setError("Máximo de 45 colunas extras atingido.");
      return;
    }
    setColumnMapping((current) => ({ ...current, [auxKey]: columnName }));
    setAuxValues((current) => ({ ...current, [auxKey]: "" }));
    setError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");

    const nome = formValues.nome_cliente?.trim();
    if (!nome) {
      setError("Nome do cliente é obrigatório.");
      return;
    }
    if (!campaignId) {
      setError("Selecione uma campanha.");
      return;
    }
    if (!selectedCampaign) {
      setError("Campanha inválida.");
      return;
    }

    if (isNewBase) {
      if (!dataRecebimento) {
        setError("Informe a data de recebimento da base.");
        return;
      }
      if (selectedChannels.length === 0) {
        setError("Selecione ao menos um canal para a nova base.");
        return;
      }
    } else if (!selectedExistingBase) {
      setError("Selecione uma base manual válida.");
      return;
    }

    setSubmitting(true);

    const creatingNewBase = baseSelection === NEW_BASE_VALUE;

    try {
      let leadBaseId: string;
      let originalMapping: Record<string, string> = {};

      if (creatingNewBase) {
        const basePayload: Record<string, unknown> = {
          campaign_id: campaignId,
          data_recebimento: dataRecebimento,
          channel_types: selectedChannels,
          column_mapping: columnMapping,
        };
        if (dataInicio) {
          basePayload.data_inicio = dataInicio;
        }
        if (dataFim) {
          basePayload.data_fim = dataFim;
        }

        const baseRes = await apiFetch("/api/v1/lead-bases/", {
          method: "POST",
          body: JSON.stringify(basePayload),
        });
        if (!baseRes.ok) {
          const data = await baseRes.json().catch(() => null);
          setError(
            formatApiDetail(data) ||
              "Erro ao criar a base de leads. O lead não foi cadastrado.",
          );
          return;
        }
        const baseBody: LeadBase = await baseRes.json();
        leadBaseId = baseBody.id;
        setBaseSelection(leadBaseId);
        await onBasesChanged?.();
      } else {
        const existingBase =
          manualBasesForCampaign.find((b) => b.id === baseSelection) ??
          leadBases.find((b) => b.id === baseSelection && isManualBase(b));
        if (!existingBase) {
          setError("Selecione uma base manual válida.");
          return;
        }
        leadBaseId = existingBase.id;
        originalMapping = existingBase.column_mapping ?? {};

        const mappingChanged =
          JSON.stringify(columnMapping) !== JSON.stringify(originalMapping);
        if (mappingChanged) {
          const mappingRes = await apiFetch(
            `/api/v1/lead-bases/${leadBaseId}/column-mapping`,
            {
              method: "PATCH",
              body: JSON.stringify({ column_mapping: columnMapping }),
            },
          );
          if (!mappingRes.ok) {
            const data = await mappingRes.json().catch(() => null);
            setError(formatApiDetail(data) || "Erro ao atualizar colunas da base.");
            return;
          }
          onColumnMappingUpdated?.(leadBaseId, columnMapping);
        }
      }

      const leadPayload = {
        lead_base_id: leadBaseId,
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

      const leadRes = await apiFetch("/api/v1/leads/", {
        method: "POST",
        body: JSON.stringify(leadPayload),
      });

      if (!leadRes.ok) {
        const data = await leadRes.json().catch(() => null);
        const detail = formatApiDetail(data);
        setError(
          detail
            ? `Falha ao cadastrar o lead: ${detail}${
                creatingNewBase ? " A base já foi criada — corrija os dados e salve novamente." : ""
              }`
            : `Falha ao cadastrar o lead.${
                creatingNewBase ? " A base já foi criada — corrija os dados e salve novamente." : ""
              }`,
        );
        return;
      }

      setFormValues({});
      setAuxValues({});
      onSuccess(leadBaseId);
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  const auxKeys = sortAuxKeys(Object.keys(columnMapping));

  if (loadingCampaigns) {
    return (
      <div className="glass-card p-6 text-sm text-muted-foreground">
        Carregando campanhas...
      </div>
    );
  }

  if (campaigns.length === 0) {
    return (
      <div className="glass-card p-6">
        <Alert variant="warning">
          Nenhuma campanha disponível. Cadastre uma campanha com canais antes de adicionar leads
          manualmente.
        </Alert>
        {onCancel && (
          <button type="button" className="btn-secondary mt-4" onClick={onCancel}>
            Fechar
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="glass-card p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">Novo lead manual</h2>
        {onCancel && (
          <button type="button" className="btn-secondary text-sm" onClick={onCancel}>
            Fechar
          </button>
        )}
      </div>

      {error && <Alert>{error}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="space-y-4 rounded-xl border border-border p-4">
          <h3 className="text-sm font-semibold text-foreground">Campanha e base</h3>

          <div>
            <label htmlFor="leadCampaign" className="mb-2 block text-sm font-medium text-foreground">
              Campanha
            </label>
            <select
              id="leadCampaign"
              value={campaignId}
              onChange={(event) => handleCampaignChange(event.target.value)}
              className="input-field max-w-xl"
            >
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name}
                  {campaign.is_system ? " (sistema)" : ""}
                </option>
              ))}
            </select>
            {selectedCampaign?.is_system && (
              <div className="mt-2">
                <SystemBadge />
              </div>
            )}
          </div>

          <div>
            <label htmlFor="leadBaseSelect" className="mb-2 block text-sm font-medium text-foreground">
              Base de destino
            </label>
            <select
              id="leadBaseSelect"
              value={baseSelection}
              onChange={(event) => {
                setBaseSelection(event.target.value);
                setError("");
              }}
              className="input-field max-w-xl"
            >
              {manualBasesForCampaign.map((base) => (
                <option key={base.id} value={base.id}>
                  {base.data_recebimento} — {base.leads_count} lead(s) —{" "}
                  {base.channel_types.join(", ")}
                </option>
              ))}
              <option value={NEW_BASE_VALUE}>➕ Criar nova base</option>
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Bases importadas via CSV não aparecem aqui (somente leitura).
            </p>
          </div>

          {isNewBase && selectedCampaign && (
            <div className="space-y-4 border-t border-border pt-4">
              <p className="text-sm text-muted-foreground">
                Dados mínimos da nova base (campanha:{" "}
                <strong className="text-foreground">{selectedCampaign.name}</strong>).
              </p>
              <div className="grid gap-4 md:grid-cols-3">
                <div>
                  <label
                    htmlFor="dataRecebimento"
                    className="mb-2 block text-sm font-medium text-foreground"
                  >
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
                  <label
                    htmlFor="dataInicio"
                    className="mb-2 block text-sm font-medium text-foreground"
                  >
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
                  <label
                    htmlFor="dataFim"
                    className="mb-2 block text-sm font-medium text-foreground"
                  >
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
                <p className="mb-2 text-sm font-medium text-foreground">Canais da base *</p>
                <div className="flex flex-wrap gap-3">
                  {selectedCampaign.channel_types.map((channel) => (
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
            </div>
          )}
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Dados do lead</h3>
          <div className="grid gap-4 md:grid-cols-2">
            {FIXED_LEAD_COLUMNS.map((column) => (
              <div key={column.key}>
                <label
                  htmlFor={`lead-${column.key}`}
                  className="mb-2 block text-sm font-medium text-foreground"
                >
                  {column.label}
                  {column.key === "nome_cliente" && " *"}
                </label>
                <input
                  id={`lead-${column.key}`}
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
                    htmlFor={`lead-${auxKey}`}
                    className="mb-2 block text-sm font-medium text-foreground"
                  >
                    {columnMapping[auxKey]}
                  </label>
                  <input
                    id={`lead-${auxKey}`}
                    type="text"
                    value={auxValues[auxKey] ?? ""}
                    onChange={(event) => updateAuxField(auxKey, event.target.value)}
                    className="input-field"
                  />
                </div>
              ))}
            </div>
          )}
        </section>

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
