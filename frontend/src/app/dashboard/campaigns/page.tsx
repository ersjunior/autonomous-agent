"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

type ChannelType = "WHATSAPP" | "TELEGRAM" | "VOICE" | "VIDEO";

interface Agent {
  id: string;
  name: string;
}

interface Campaign {
  id: string;
  name: string;
  agent_id: string;
  channel_types: string[];
  status: string;
  leads_count: number;
  created_at: string;
}

const CHANNEL_TYPES: ChannelType[] = ["WHATSAPP", "TELEGRAM", "VOICE", "VIDEO"];

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [channelTypes, setChannelTypes] = useState<ChannelType[]>(["WHATSAPP"]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function loadData() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      const [campaignsRes, agentsRes] = await Promise.all([
        apiFetch("/api/v1/campaigns/"),
        apiFetch("/api/v1/agents/"),
      ]);

      if (campaignsRes.ok) {
        setCampaigns(await campaignsRes.json());
      }
      if (agentsRes.ok) {
        const agentsData: Agent[] = await agentsRes.json();
        setAgents(agentsData);
        if (agentsData.length > 0 && !agentId) {
          setAgentId(agentsData[0].id);
        }
      }
    } catch {
      setError("Erro ao carregar campanhas.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const res = await apiFetch("/api/v1/campaigns/", {
        method: "POST",
        body: JSON.stringify({
          name,
          agent_id: agentId,
          channel_types: channelTypes.map((type) => type.toLowerCase()),
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Erro ao criar campanha.");
        return;
      }

      setShowForm(false);
      setName("");
      setChannelTypes(["WHATSAPP"]);
      await loadData();
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  function getAgentName(id: string) {
    return agents.find((a) => a.id === id)?.name ?? id;
  }

  return (
    <>
      <PageHeader
        title="Campanhas"
        description="Gerencie campanhas ativas e receptivas."
        actions={
          <button
            type="button"
            onClick={() => setShowForm(!showForm)}
            disabled={agents.length === 0}
            className="btn-primary"
          >
            {showForm ? "Cancelar" : "Nova campanha"}
          </button>
        }
      />

      {agents.length === 0 && !loading && (
        <Alert variant="warning">Cadastre um agente antes de criar uma campanha.</Alert>
      )}

      {error && <Alert>{error}</Alert>}

      {showForm && agents.length > 0 && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Nova campanha</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="mb-2 block text-sm font-medium text-foreground">
                Nome
              </label>
              <input
                id="name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input-field"
              />
            </div>

            <div>
              <label htmlFor="agentId" className="mb-2 block text-sm font-medium text-foreground">
                Agente
              </label>
              <select
                id="agentId"
                required
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="input-field"
              >
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <p className="mb-2 block text-sm font-medium text-foreground">Canais</p>
              <div className="flex flex-wrap gap-3">
                {CHANNEL_TYPES.map((type) => (
                  <label key={type} className="flex items-center gap-2 text-sm text-foreground">
                    <input
                      type="checkbox"
                      checked={channelTypes.includes(type)}
                      onChange={() =>
                        setChannelTypes((current) =>
                          current.includes(type)
                            ? current.filter((item) => item !== type)
                            : [...current, type],
                        )
                      }
                    />
                    {type}
                  </label>
                ))}
              </div>
            </div>

            <button type="submit" disabled={submitting || channelTypes.length === 0} className="btn-primary">
              {submitting ? "Salvando..." : "Salvar campanha"}
            </button>
          </form>
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
                {["Nome", "Agente", "Canal", "Status", "Leads"].map((col) => (
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
              {campaigns.map((campaign) => (
                <tr key={campaign.id} className="transition hover:bg-muted/30">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-foreground">
                    {campaign.name}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                    {getAgentName(campaign.agent_id)}
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
