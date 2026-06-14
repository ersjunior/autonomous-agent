"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  createCampaign,
  deleteCampaign,
  fetchAgents,
  fetchCampaigns,
  startCampaign,
  stopCampaign,
  updateCampaign,
} from "@/lib/api-entities";
import { actionsFor } from "@/lib/protection";
import type { Agent } from "@/lib/types/agents";
import type { Campaign } from "@/lib/types/campaigns";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

type ChannelType = "WHATSAPP" | "TELEGRAM" | "VOICE";
const CHANNEL_TYPES: ChannelType[] = ["WHATSAPP", "TELEGRAM", "VOICE"];

type FormMode = "create" | "edit" | "view" | null;

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [channelTypes, setChannelTypes] = useState<ChannelType[]>(["WHATSAPP"]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Campaign | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [startingId, setStartingId] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);

  async function loadData() {
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
      if (agentsData.length > 0 && !agentId) {
        setAgentId(agentsData[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar campanhas.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  function openCreate() {
    setSelected(null);
    setName("");
    setChannelTypes(["WHATSAPP"]);
    if (agents.length > 0) {
      setAgentId(agents[0].id);
    }
    setFormMode("create");
    setError("");
    setSuccess("");
  }

  function openCampaign(campaign: Campaign, mode: "view" | "edit") {
    setSelected(campaign);
    setName(campaign.name);
    setAgentId(campaign.agent_id);
    setChannelTypes(
      (campaign.channel_types.length
        ? campaign.channel_types.map((c) => c.toUpperCase() as ChannelType)
        : ["WHATSAPP"]) as ChannelType[],
    );
    setFormMode(mode);
    setError("");
  }

  function closeForm() {
    setFormMode(null);
    setSelected(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setSubmitting(true);

    const payload = {
      name,
      agent_id: agentId,
      channel_types: channelTypes.map((t) => t.toLowerCase()),
    };

    try {
      if (formMode === "create") {
        await createCampaign(payload);
        setSuccess("Campanha criada com sucesso.");
        setFormMode(null);
      } else if (formMode === "edit" && selected) {
        await updateCampaign(selected.id, payload);
        setSuccess("Campanha atualizada.");
        closeForm();
      }
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar campanha.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStart(campaign: Campaign) {
    setStartingId(campaign.id);
    setError("");
    setSuccess("");
    try {
      const result = await startCampaign(campaign.id);
      setSuccess(
        `Campanha iniciada. ${result.leads_dispatched} lead(s) enfileirado(s) para disparo.`,
      );
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao iniciar campanha.");
    } finally {
      setStartingId(null);
    }
  }

  async function handleStop(campaign: Campaign) {
    setStoppingId(campaign.id);
    setError("");
    setSuccess("");
    try {
      const result = await stopCampaign(campaign.id);
      setSuccess(
        `Campanha pausada. ${result.activations_stopped} canal(is) desligado(s).`,
      );
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao parar campanha.");
    } finally {
      setStoppingId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteCampaign(deleteTarget.id);
      setSuccess("Campanha excluída.");
      setDeleteTarget(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir campanha.");
    } finally {
      setDeleting(false);
    }
  }

  function getAgentName(id: string) {
    return agents.find((a) => a.id === id)?.name ?? id;
  }

  function getAgentMode(id: string) {
    return agents.find((a) => a.id === id)?.mode;
  }

  const readOnly = formMode === "view";
  const showInlineForm = formMode === "create";

  return (
    <>
      <PageHeader
        title="Campanhas"
        description="Gerencie campanhas ativas e receptivas."
        actions={
          <button
            type="button"
            onClick={() => (showInlineForm ? closeForm() : openCreate())}
            disabled={agents.length === 0}
            className="btn-primary"
          >
            {showInlineForm ? "Cancelar" : "Nova campanha"}
          </button>
        }
      />

      {agents.length === 0 && !loading && (
        <Alert variant="warning">Cadastre um agente antes de criar uma campanha.</Alert>
      )}

      {error && <Alert>{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      {showInlineForm && agents.length > 0 && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Nova campanha</h2>
          <CampaignForm
            name={name}
            agentId={agentId}
            agents={agents}
            channelTypes={channelTypes}
            readOnly={false}
            onNameChange={setName}
            onAgentChange={setAgentId}
            onChannelToggle={(type) =>
              setChannelTypes((current) =>
                current.includes(type)
                  ? current.filter((item) => item !== type)
                  : [...current, type],
              )
            }
            onSubmit={handleSubmit}
            submitting={submitting}
          />
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Carregando campanhas...</p>
      ) : campaigns.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhuma campanha cadastrada.
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted/50">
              <tr>
                {["Nome", "Agente", "Canal", "Status", "Leads", "Ações"].map((col) => (
                  <th
                    key={col}
                    className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {campaigns.map((campaign) => {
                const actions = actionsFor(campaign);
                const agentMode = getAgentMode(campaign.agent_id);
                const canStart =
                  actions.canEdit &&
                  (campaign.status === "draft" || campaign.status === "paused");
                const canStop = actions.canEdit && campaign.status === "active";
                return (
                  <tr key={campaign.id} className="transition hover:bg-muted/30">
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-foreground">{campaign.name}</span>
                        {campaign.is_system && <SystemBadge />}
                      </div>
                      {agentMode === "RECEPTIVE" && (
                        <p className="mt-1 text-xs text-warning">
                          Agente RECEPTIVE: disparo outbound será bloqueado
                        </p>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                      {getAgentName(campaign.agent_id)}
                      {agentMode && (
                        <span className="ml-1 text-xs text-muted-foreground">({agentMode})</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {campaign.channel_types.join(", ").toUpperCase() || "—"}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <Badge>{campaign.status}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                      {campaign.leads_count}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <RecordActionsBar
                        actions={actions}
                        onView={() => openCampaign(campaign, "view")}
                        onEdit={() => openCampaign(campaign, "edit")}
                        onDelete={() => setDeleteTarget(campaign)}
                        onStart={canStart ? () => handleStart(campaign) : undefined}
                        onStop={canStop ? () => handleStop(campaign) : undefined}
                        startLoading={startingId === campaign.id}
                        stopLoading={stoppingId === campaign.id}
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
        open={formMode === "view" || formMode === "edit"}
        title={formMode === "view" ? "Visualizar campanha" : "Editar campanha"}
        onClose={closeForm}
        wide
      >
        <CampaignForm
          name={name}
          agentId={agentId}
          agents={agents}
          channelTypes={channelTypes}
          readOnly={readOnly}
          onNameChange={setName}
          onAgentChange={setAgentId}
          onChannelToggle={(type) =>
            setChannelTypes((current) =>
              current.includes(type)
                ? current.filter((item) => item !== type)
                : [...current, type],
            )
          }
          onSubmit={handleSubmit}
          submitting={submitting}
          hideSubmit={readOnly}
        />
      </Modal>

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir campanha"
        message={`Tem certeza que deseja excluir a campanha "${deleteTarget?.name}"?`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function CampaignForm({
  name,
  agentId,
  agents,
  channelTypes,
  readOnly,
  onNameChange,
  onAgentChange,
  onChannelToggle,
  onSubmit,
  submitting,
  hideSubmit = false,
}: {
  name: string;
  agentId: string;
  agents: Agent[];
  channelTypes: ChannelType[];
  readOnly: boolean;
  onNameChange: (v: string) => void;
  onAgentChange: (v: string) => void;
  onChannelToggle: (type: ChannelType) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
  hideSubmit?: boolean;
}) {
  const selectedAgent = agents.find((a) => a.id === agentId);

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label className="mb-2 block text-sm font-medium text-foreground">Nome</label>
        <input
          type="text"
          required
          disabled={readOnly}
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          className="input-field disabled:opacity-70"
        />
      </div>

      <div>
        <label className="mb-2 block text-sm font-medium text-foreground">Agente</label>
        <select
          required
          disabled={readOnly}
          value={agentId}
          onChange={(e) => onAgentChange(e.target.value)}
          className="input-field disabled:opacity-70"
        >
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
              {agent.is_system ? " (sistema)" : ""} — {agent.mode}
            </option>
          ))}
        </select>
        {selectedAgent?.mode === "RECEPTIVE" && !readOnly && (
          <p className="mt-2 text-xs text-warning">
            Este agente é RECEPTIVE: o disparo outbound será bloqueado ao iniciar a campanha.
          </p>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-foreground">Canais</p>
        <div className="flex flex-wrap gap-3">
          {CHANNEL_TYPES.map((type) => (
            <label key={type} className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                disabled={readOnly}
                checked={channelTypes.includes(type)}
                onChange={() => onChannelToggle(type)}
              />
              {type}
            </label>
          ))}
        </div>
      </div>

      {!hideSubmit && (
        <button
          type="submit"
          disabled={submitting || channelTypes.length === 0}
          className="btn-primary"
        >
          {submitting ? "Salvando..." : "Salvar campanha"}
        </button>
      )}
    </form>
  );
}
