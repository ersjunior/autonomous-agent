"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getTabulacaoCatalog, type TabulacaoCatalogItem } from "@/lib/api";
import {
  fetchActivationHistory,
  finalizeInteraction,
  getActivations,
  getChannelSettings,
  startActivation,
  stopActivation,
  testDispatch,
  updateChannelSettings,
} from "@/lib/api-activation";
import { fetchAgents, fetchCampaigns, fetchLeads } from "@/lib/api-entities";
import type {
  Activation,
  ActivationHistoryItem,
  TestDispatchResult,
} from "@/lib/types/activation";
import type { Agent } from "@/lib/types/agents";
import type { Campaign } from "@/lib/types/campaigns";
import type { Lead } from "@/lib/types/leads";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { SystemBadge } from "@/components/ui/SystemBadge";

const VOICE_CHANNELS = new Set(["voice"]);
const MESSAGING = new Set(["whatsapp", "telegram"]);
const TEST_CHANNELS = ["whatsapp", "telegram", "voice"] as const;
const HISTORY_CHANNELS = ["whatsapp", "telegram", "voice"] as const;
const HISTORY_LIMIT = 50;
const FINALIZE_CATEGORIES = new Set(["NEGOCIO", "CUSTOMIZADO"]);
const HISTORY_STATUS_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "pendente", label: "Pendente" },
  { value: "acionado", label: "Acionado" },
  { value: "em_andamento", label: "Em andamento" },
  { value: "convertido", label: "Convertido" },
  { value: "recusou", label: "Recusou" },
  { value: "nao_atendido", label: "Não atendido" },
  { value: "erro", label: "Erro" },
] as const;

type TabId = "motor" | "test" | "history";

function channelLabel(channel: string): string {
  return channel.toUpperCase();
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  return new Date(iso).toLocaleString("pt-BR");
}

function statusBadgeVariant(
  status: string,
): "default" | "warning" | "success" | "muted" {
  const s = status.toLowerCase();
  if (s === "convertido") {
    return "success";
  }
  if (s === "em_andamento" || s === "acionado") {
    return "default";
  }
  if (s === "recusou" || s === "nao_atendido" || s === "erro") {
    return "warning";
  }
  return "muted";
}

function isVoiceChannel(channel: string): boolean {
  return VOICE_CHANNELS.has(channel.toLowerCase());
}

type ParamsState = Record<string, Record<string, string | number>>;

export default function ActivationPage() {
  const [activeTab, setActiveTab] = useState<TabId>("motor");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [activations, setActivations] = useState<Activation[]>([]);
  const [paramsByChannel, setParamsByChannel] = useState<ParamsState>({});
  const [editable, setEditable] = useState(false);
  const [agentIsSystem, setAgentIsSystem] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [savingChannel, setSavingChannel] = useState<string | null>(null);
  const [togglingChannel, setTogglingChannel] = useState<string | null>(null);

  const selectedCampaign = useMemo(
    () => campaigns.find((c) => c.id === campaignId) ?? null,
    [campaigns, campaignId],
  );

  const selectedAgent = useMemo(
    () =>
      selectedCampaign
        ? agents.find((a) => a.id === selectedCampaign.agent_id) ?? null
        : null,
    [agents, selectedCampaign],
  );

  const campaignChannels = useMemo(() => {
    if (!selectedCampaign) {
      return [];
    }
    return selectedCampaign.channel_types.map((c) => c.toLowerCase());
  }, [selectedCampaign]);

  const activationMap = useMemo(() => {
    const map: Record<string, Activation> = {};
    for (const a of activations) {
      map[a.channel_type.toLowerCase()] = a;
    }
    return map;
  }, [activations]);

  async function loadCampaignsAndAgents() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }
    try {
      const [campaignsData, agentsData] = await Promise.all([
        fetchCampaigns(),
        fetchAgents(),
      ]);
      setCampaigns(campaignsData);
      setAgents(agentsData);
      if (campaignsData.length > 0 && !campaignId) {
        setCampaignId(campaignsData[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar dados.");
    } finally {
      setLoading(false);
    }
  }

  const loadCampaignDetail = useCallback(async () => {
    if (!selectedCampaign || !selectedAgent) {
      return;
    }
    setLoadingDetail(true);
    setError("");
    try {
      const [activationList, settingsList] = await Promise.all([
        getActivations(selectedCampaign.id),
        getChannelSettings(selectedAgent.id),
      ]);
      setActivations(activationList.activations);
      setEditable(settingsList.editable);
      setAgentIsSystem(settingsList.is_system);

      const nextParams: ParamsState = {};
      for (const ch of settingsList.channels) {
        const key = ch.channel_type.toLowerCase();
        nextParams[key] = { ...ch.params };
      }
      setParamsByChannel(nextParams);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar acionamento.");
    } finally {
      setLoadingDetail(false);
    }
  }, [selectedCampaign, selectedAgent]);

  useEffect(() => {
    loadCampaignsAndAgents();
  }, []);

  useEffect(() => {
    if (campaignId && selectedCampaign && selectedAgent) {
      loadCampaignDetail();
    }
  }, [campaignId, selectedCampaign?.id, selectedAgent?.id, loadCampaignDetail]);

  function updateParam(channel: string, key: string, value: string | number) {
    setParamsByChannel((prev) => ({
      ...prev,
      [channel]: { ...prev[channel], [key]: value },
    }));
  }

  async function handleSaveParams(channel: string) {
    if (!selectedAgent) {
      return;
    }
    setSavingChannel(channel);
    setError("");
    setSuccess("");
    try {
      const params = paramsByChannel[channel];
      await updateChannelSettings(selectedAgent.id, channel, params);
      setSuccess(`Parâmetros de ${channelLabel(channel)} salvos.`);
      await loadCampaignDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar parâmetros.");
    } finally {
      setSavingChannel(null);
    }
  }

  async function handleStart(channel: string) {
    if (!selectedCampaign) {
      return;
    }
    setTogglingChannel(channel);
    setError("");
    setSuccess("");
    try {
      const result = await startActivation(selectedCampaign.id, channel);
      setSuccess(
        `${channelLabel(channel)} ligado — ${result.leads_dispatched} lead(s) enfileirado(s).`,
      );
      await loadCampaignDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao iniciar canal.");
    } finally {
      setTogglingChannel(null);
    }
  }

  async function handleStop(channel: string) {
    if (!selectedCampaign) {
      return;
    }
    setTogglingChannel(channel);
    setError("");
    setSuccess("");
    try {
      await stopActivation(selectedCampaign.id, channel);
      setSuccess(`${channelLabel(channel)} desligado. Tasks já na fila não são canceladas.`);
      await loadCampaignDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao parar canal.");
    } finally {
      setTogglingChannel(null);
    }
  }

  function renderVoiceFields(channel: string, readOnly: boolean) {
    const p = paramsByChannel[channel] ?? {};
    const fields = [
      { key: "chamadas_simultaneas", label: "Chamadas simultâneas", min: 1 },
      { key: "campanhas_simultaneas", label: "Campanhas simultâneas", min: 1 },
      { key: "tentativas_por_hora", label: "Tentativas por hora", min: 0 },
    ] as const;
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(({ key, label, min }) => (
          <label key={key} className="block text-sm">
            <span className="text-muted-foreground">{label}</span>
            <input
              type="number"
              min={min}
              disabled={readOnly}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
              value={p[key] ?? ""}
              onChange={(e) =>
                updateParam(channel, key, parseInt(e.target.value, 10) || min)
              }
            />
          </label>
        ))}
        <label className="block text-sm">
          <span className="text-muted-foreground">Horário início</span>
          <input
            type="time"
            disabled={readOnly}
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
            value={String(p.horario_inicio ?? "09:00")}
            onChange={(e) => updateParam(channel, "horario_inicio", e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">Horário fim</span>
          <input
            type="time"
            disabled={readOnly}
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
            value={String(p.horario_fim ?? "20:00")}
            onChange={(e) => updateParam(channel, "horario_fim", e.target.value)}
          />
        </label>
      </div>
    );
  }

  function renderMessagingFields(channel: string, readOnly: boolean) {
    const p = paramsByChannel[channel] ?? {};
    const fields = [
      { key: "chats_simultaneos", label: "Chats simultâneos", min: 1 },
      { key: "campanhas_simultaneas", label: "Campanhas simultâneas", min: 1 },
      { key: "tentativas_sem_resposta", label: "Tentativas sem resposta", min: 0 },
      { key: "minutos_segunda_mensagem", label: "Minutos 2ª mensagem", min: 0 },
    ] as const;
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(({ key, label, min }) => (
          <label key={key} className="block text-sm">
            <span className="text-muted-foreground">{label}</span>
            <input
              type="number"
              min={min}
              disabled={readOnly}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
              value={p[key] ?? ""}
              onChange={(e) =>
                updateParam(channel, key, parseInt(e.target.value, 10) || min)
              }
            />
          </label>
        ))}
        <label className="block text-sm">
          <span className="text-muted-foreground">Horário início</span>
          <input
            type="time"
            disabled={readOnly}
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
            value={String(p.horario_inicio ?? "09:00")}
            onChange={(e) => updateParam(channel, "horario_inicio", e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">Horário fim</span>
          <input
            type="time"
            disabled={readOnly}
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-60"
            value={String(p.horario_fim ?? "20:00")}
            onChange={(e) => updateParam(channel, "horario_fim", e.target.value)}
          />
        </label>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-muted-foreground">
        Carregando…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Acionamento"
        description="Motor de campanha, teste ad-hoc ou histórico de acionamentos outbound."
      />

      <div className="flex flex-wrap gap-2 border-b border-border">
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "motor"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("motor")}
        >
          Motor de campanha
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "test"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("test")}
        >
          Teste de acionamento
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "history"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("history")}
        >
          Histórico de acionamentos
        </button>
      </div>

      {activeTab === "test" ? (
        <TestActivationPanel agents={agents} />
      ) : activeTab === "history" ? (
        <ActivationHistoryPanel campaigns={campaigns} />
      ) : (
        <>
      {error && <Alert variant="error">{error}</Alert>}
      {success && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">
          {success}
        </div>
      )}

      <div className="glass-card p-6">
        <label className="block text-sm font-medium text-foreground">Campanha</label>
        <select
          className="mt-2 w-full max-w-xl rounded-lg border border-border bg-background px-3 py-2 text-sm"
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
        >
          {campaigns.length === 0 ? (
            <option value="">Nenhuma campanha</option>
          ) : (
            campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.is_system ? " (sistema)" : ""}
              </option>
            ))
          )}
        </select>

        {selectedCampaign && selectedAgent && (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>
              Agente: <strong className="text-foreground">{selectedAgent.name}</strong> (
              {selectedAgent.mode})
            </span>
            {agentIsSystem && <SystemBadge />}
            {selectedAgent.mode !== "ACTIVE" && (
              <Badge variant="warning">Apenas agentes ACTIVE disparam outbound</Badge>
            )}
          </div>
        )}

        {agentIsSystem && (
          <p className="mt-4 text-sm text-muted-foreground">
            Parâmetros padrão do sistema (somente leitura).{" "}
            <Link href="/dashboard/agents" className="font-medium text-primary hover:underline">
              Criar agente personalizável
            </Link>
          </p>
        )}
      </div>

      {loadingDetail && (
        <p className="text-sm text-muted-foreground">Atualizando canais…</p>
      )}

      {!selectedCampaign ? null : campaignChannels.length === 0 ? (
        <div className="glass-card p-6 text-sm text-muted-foreground">
          Esta campanha não tem canais configurados.
        </div>
      ) : (
        <div className="space-y-6">
          {campaignChannels.map((channel) => {
            const activation = activationMap[channel];
            const running = activation?.is_running ?? false;
            const readOnly = !editable;
            const canToggle =
              !selectedCampaign.is_system && selectedAgent?.mode === "ACTIVE";

            return (
              <section key={channel} className="glass-card space-y-4 p-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold text-foreground">
                      {channelLabel(channel)}
                    </h2>
                    <Badge variant={running ? "success" : "muted"}>
                      {running ? "Ligado" : "Desligado"}
                    </Badge>
                    {readOnly && (
                      <span className="text-xs text-muted-foreground">Padrão do sistema</span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {running ? (
                      <button
                        type="button"
                        disabled={!canToggle || togglingChannel === channel}
                        className="rounded-lg border border-border px-4 py-2 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
                        onClick={() => handleStop(channel)}
                      >
                        {togglingChannel === channel ? "Parando…" : "Parar"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={!canToggle || togglingChannel === channel}
                        className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
                        onClick={() => handleStart(channel)}
                      >
                        {togglingChannel === channel ? "Iniciando…" : "Iniciar"}
                      </button>
                    )}
                  </div>
                </div>

                {activation?.started_at && (
                  <p className="text-xs text-muted-foreground">
                    Último start: {new Date(activation.started_at).toLocaleString("pt-BR")}
                  </p>
                )}

                {isVoiceChannel(channel) || MESSAGING.has(channel) ? (
                  isVoiceChannel(channel)
                    ? renderVoiceFields(channel, readOnly)
                    : renderMessagingFields(channel, readOnly)
                ) : (
                  <p className="text-sm text-warning">Canal não suportado nesta camada.</p>
                )}

                {editable && (
                  <button
                    type="button"
                    disabled={savingChannel === channel}
                    className="rounded-lg border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition hover:bg-primary/20 disabled:opacity-50"
                    onClick={() => handleSaveParams(channel)}
                  >
                    {savingChannel === channel ? "Salvando…" : "Salvar parâmetros"}
                  </button>
                )}
              </section>
            );
          })}
        </div>
      )}
        </>
      )}
    </div>
  );
}

function leadOptionLabel(lead: Lead): string {
  const phone = lead.telefone_1 || lead.telefone_2 || lead.telefone_3;
  const telegram = lead.aux_values?.telegram_id;
  const contact = phone || (telegram ? `tg:${telegram}` : "sem contato");
  return `${lead.nome_cliente} — ${contact}`;
}

function TestActivationPanel({ agents }: { agents: Agent[] }) {
  const activeAgents = useMemo(
    () => agents.filter((a) => a.mode === "ACTIVE"),
    [agents],
  );
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(true);
  const [agentId, setAgentId] = useState("");
  const [leadId, setLeadId] = useState("");
  const [channelType, setChannelType] = useState<string>(TEST_CHANNELS[0]);
  const [dispatching, setDispatching] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<TestDispatchResult | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchLeads();
        setLeads(data);
        if (data.length > 0) {
          setLeadId(data[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao carregar leads.");
      } finally {
        setLoadingLeads(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (activeAgents.length > 0 && !agentId) {
      setAgentId(activeAgents[0].id);
    }
  }, [activeAgents, agentId]);

  async function handleDispatch() {
    if (!agentId || !leadId) {
      return;
    }
    setDispatching(true);
    setError("");
    setResult(null);
    try {
      const response = await testDispatch({
        lead_id: leadId,
        agent_id: agentId,
        channel_type: channelType,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro no disparo de teste.");
    } finally {
      setDispatching(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="error">{error}</Alert>}

      <div className="glass-card space-y-5 p-6">
        <p className="text-sm text-muted-foreground">
          Dispara um acionamento único com agente, lead e canal escolhidos. O resultado aparece
          abaixo assim que o LLM e o canal concluírem (pode levar dezenas de segundos).
        </p>

        <label className="block text-sm font-medium text-foreground">
          Agente (ACTIVE)
          <select
            className="mt-2 w-full max-w-xl rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            disabled={activeAgents.length === 0}
          >
            {activeAgents.length === 0 ? (
              <option value="">Nenhum agente ACTIVE</option>
            ) : (
              activeAgents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.is_system ? " (sistema)" : ""}
                </option>
              ))
            )}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Lead
          <select
            className="mt-2 w-full max-w-xl rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={leadId}
            onChange={(e) => setLeadId(e.target.value)}
            disabled={loadingLeads || leads.length === 0}
          >
            {loadingLeads ? (
              <option value="">Carregando…</option>
            ) : leads.length === 0 ? (
              <option value="">Nenhum lead</option>
            ) : (
              leads.map((l) => (
                <option key={l.id} value={l.id}>
                  {leadOptionLabel(l)}
                </option>
              ))
            )}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Canal
          <select
            className="mt-2 w-full max-w-xl rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={channelType}
            onChange={(e) => setChannelType(e.target.value)}
          >
            {TEST_CHANNELS.map((ch) => (
              <option key={ch} value={ch}>
                {channelLabel(ch)}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          disabled={dispatching || !agentId || !leadId}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
          onClick={handleDispatch}
        >
          {dispatching ? "Disparando…" : "Disparar"}
        </button>
      </div>

      {result && (
        <div className="glass-card space-y-4 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-foreground">Resultado</h2>
            <Badge variant={result.status === "sucesso" ? "success" : "warning"}>
              {result.status}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Canal: <strong className="text-foreground">{result.channel.toUpperCase()}</strong>
            {result.recipient && (
              <>
                {" "}
                · Destinatário:{" "}
                <strong className="text-foreground">{result.recipient}</strong>
              </>
            )}
          </p>
          {result.lead_interaction_id && (
            <p className="text-xs text-muted-foreground">
              LeadInteraction: {result.lead_interaction_id}
            </p>
          )}
          {result.error && <Alert variant="error">{result.error}</Alert>}
          {result.response && (
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Resposta gerada</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-4 text-sm text-foreground">
                {result.response}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ActivationHistoryPanel({ campaigns }: { campaigns: Campaign[] }) {
  const [items, setItems] = useState<ActivationHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterCampaignId, setFilterCampaignId] = useState("");
  const [filterChannel, setFilterChannel] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [finalizeTarget, setFinalizeTarget] = useState<ActivationHistoryItem | null>(null);
  const [tabulacoes, setTabulacoes] = useState<TabulacaoCatalogItem[]>([]);
  const [selectedTabulacao, setSelectedTabulacao] = useState("");
  const [finalizeLoading, setFinalizeLoading] = useState(false);

  const currentPage = Math.floor(skip / HISTORY_LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_LIMIT));
  const canPrev = skip > 0;
  const canNext = skip + HISTORY_LIMIT < total;

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchActivationHistory(skip, HISTORY_LIMIT, {
        campaign_id: filterCampaignId || undefined,
        channel_type: filterChannel || undefined,
        status: filterStatus || undefined,
        open_only: openOnly,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar histórico.");
    } finally {
      setLoading(false);
    }
  }, [skip, filterCampaignId, filterChannel, filterStatus, openOnly]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    async function loadTabulacoes() {
      try {
        const res = await getTabulacaoCatalog();
        if (!res.ok) {
          return;
        }
        const data = (await res.json()) as TabulacaoCatalogItem[];
        setTabulacoes(
          data.filter((t) => FINALIZE_CATEGORIES.has(t.categoria.toUpperCase())),
        );
      } catch {
        // modal exibirá lista vazia
      }
    }
    void loadTabulacoes();
  }, []);

  function handleFilterChange(updater: () => void) {
    updater();
    setSkip(0);
  }

  function openFinalizeModal(item: ActivationHistoryItem) {
    setFinalizeTarget(item);
    setSelectedTabulacao("");
  }

  function closeFinalizeModal() {
    setFinalizeTarget(null);
    setSelectedTabulacao("");
  }

  async function handleFinalizeConfirm() {
    if (!finalizeTarget || !selectedTabulacao) {
      return;
    }
    setFinalizeLoading(true);
    setError("");
    try {
      await finalizeInteraction(finalizeTarget.id, {
        tabulacao_codigo: selectedTabulacao,
      });
      closeFinalizeModal();
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao finalizar atendimento.");
    } finally {
      setFinalizeLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="error">{error}</Alert>}

      <div className="glass-card grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-sm font-medium text-foreground">
          Campanha
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterCampaignId}
            onChange={(e) =>
              handleFilterChange(() => setFilterCampaignId(e.target.value))
            }
          >
            <option value="">Todas</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.is_system ? " (sistema)" : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Canal
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterChannel}
            onChange={(e) => handleFilterChange(() => setFilterChannel(e.target.value))}
          >
            <option value="">Todos</option>
            {HISTORY_CHANNELS.map((ch) => (
              <option key={ch} value={ch}>
                {channelLabel(ch)}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Status
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterStatus}
            onChange={(e) => handleFilterChange(() => setFilterStatus(e.target.value))}
          >
            {HISTORY_STATUS_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-end gap-2 pb-2 text-sm font-medium text-foreground">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={openOnly}
            onChange={(e) =>
              handleFilterChange(() => setOpenOnly(e.target.checked))
            }
          />
          Só abertos
        </label>
      </div>

      <div className="glass-card overflow-x-auto">
        <table className="w-full min-w-[960px] text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-muted-foreground">
              <th className="px-4 py-3 font-medium">Lead</th>
              <th className="px-4 py-3 font-medium">Campanha</th>
              <th className="px-4 py-3 font-medium">Canal</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Tabulação</th>
              <th className="px-4 py-3 font-medium">Acionamento</th>
              <th className="px-4 py-3 font-medium">Último contato</th>
              <th className="px-4 py-3 font-medium">Tentativas</th>
              <th className="px-4 py-3 font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                  Carregando…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                  Nenhum acionamento encontrado.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-border/60 hover:bg-muted/20"
                >
                  <td className="px-4 py-3 font-medium text-foreground">
                    <span className="inline-flex flex-wrap items-center gap-2">
                      {item.lead_nome}
                      {item.is_human_mode && <Badge variant="warning">Humano</Badge>}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-foreground">{item.campaign_name}</td>
                  <td className="px-4 py-3">
                    <Badge variant="muted">{channelLabel(item.channel_type)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusBadgeVariant(item.status)}>{item.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {item.tabulacao_codigo
                      ? `${item.tabulacao_codigo} — ${item.tabulacao_nome ?? ""}`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDateTime(item.data_acionamento)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDateTime(item.data_ultimo_contato)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{item.tentativas}</td>
                  <td className="px-4 py-3">
                    {!item.is_terminal && (
                      <button
                        type="button"
                        className="rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20"
                        onClick={() => openFinalizeModal(item)}
                      >
                        Finalizar
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Exibindo {total === 0 ? 0 : skip + 1}–{Math.min(skip + HISTORY_LIMIT, total)} de{" "}
          {total} acionamentos
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={!canPrev || loading}
            onClick={() => setSkip(Math.max(0, skip - HISTORY_LIMIT))}
          >
            Anterior
          </button>
          <span className="text-sm text-muted-foreground">
            Página {currentPage} de {totalPages}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={!canNext || loading}
            onClick={() => setSkip(skip + HISTORY_LIMIT)}
          >
            Próxima
          </button>
        </div>
      </div>

      {finalizeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="glass-card w-full max-w-md space-y-4 p-6">
            <h3 className="text-lg font-semibold text-foreground">Finalizar atendimento</h3>
            <p className="text-sm text-muted-foreground">
              {finalizeTarget.lead_nome} — {channelLabel(finalizeTarget.channel_type)} — escolha
              a tabulação de encerramento.
            </p>
            <label className="block text-sm font-medium text-foreground">Tabulação</label>
            <select
              className="input-field w-full"
              value={selectedTabulacao}
              onChange={(e) => setSelectedTabulacao(e.target.value)}
            >
              <option value="">Selecione...</option>
              {tabulacoes.map((t) => (
                <option key={t.id} value={t.codigo}>
                  {t.codigo} — {t.nome}
                </option>
              ))}
            </select>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={closeFinalizeModal}
                disabled={finalizeLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void handleFinalizeConfirm()}
                disabled={finalizeLoading || !selectedTabulacao}
              >
                {finalizeLoading ? "Finalizando…" : "Confirmar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
