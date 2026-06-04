"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getActivations,
  getChannelSettings,
  startActivation,
  stopActivation,
  updateChannelSettings,
} from "@/lib/api-activation";
import { fetchAgents, fetchCampaigns } from "@/lib/api-entities";
import type { Activation } from "@/lib/types/activation";
import type { Agent } from "@/lib/types/agents";
import type { Campaign } from "@/lib/types/campaigns";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { SystemBadge } from "@/components/ui/SystemBadge";

const VOICE_VIDEO = new Set(["voice", "video"]);
const MESSAGING = new Set(["whatsapp", "telegram"]);

function channelLabel(channel: string): string {
  return channel.toUpperCase();
}

function isVoiceVideo(channel: string): boolean {
  return VOICE_VIDEO.has(channel.toLowerCase());
}

type ParamsState = Record<string, Record<string, string | number>>;

export default function ActivationPage() {
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

  function renderVoiceVideoFields(channel: string, readOnly: boolean) {
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
        description="Liga/desliga o motor por canal e ajusta parâmetros do agente (modo ATIVO). Cadência e janela de horário entram nas próximas camadas."
      />

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

                {isVoiceVideo(channel) || MESSAGING.has(channel) ? (
                  isVoiceVideo(channel)
                    ? renderVoiceVideoFields(channel, readOnly)
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
    </div>
  );
}
