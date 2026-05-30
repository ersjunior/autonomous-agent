"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type ChannelType = "WHATSAPP" | "TELEGRAM" | "VOICE" | "VIDEO";

interface Agent {
  id: string;
  name: string;
}

interface Campaign {
  id: string;
  name: string;
  agent_id: string;
  channel_type: ChannelType;
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
  const [channelType, setChannelType] = useState<ChannelType>("WHATSAPP");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function loadData() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/login";
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
          channel_type: channelType,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Erro ao criar campanha.");
        return;
      }

      setShowForm(false);
      setName("");
      setChannelType("WHATSAPP");
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
    <main className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Campanhas</h1>
          <p className="mt-1 text-gray-600">Gerencie campanhas ativas e receptivas.</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          disabled={agents.length === 0}
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {showForm ? "Cancelar" : "Nova Campanha"}
        </button>
      </div>

      {agents.length === 0 && !loading && (
        <div className="mb-4 rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
          Cadastre um agente antes de criar uma campanha.
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {showForm && agents.length > 0 && (
        <div className="mb-8 rounded-lg bg-white p-6 shadow">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Nova campanha</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
                Nome
              </label>
              <input
                id="name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="agentId" className="mb-1 block text-sm font-medium text-gray-700">
                Agente
              </label>
              <select
                id="agentId"
                required
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="channelType" className="mb-1 block text-sm font-medium text-gray-700">
                Canal
              </label>
              <select
                id="channelType"
                value={channelType}
                onChange={(e) => setChannelType(e.target.value as ChannelType)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {CHANNEL_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "Salvando..." : "Salvar campanha"}
            </button>
          </form>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Carregando campanhas...</p>
      ) : campaigns.length === 0 ? (
        <p className="text-gray-500">Nenhuma campanha cadastrada.</p>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Nome
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Agente
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Canal
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Leads
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {campaigns.map((campaign) => (
                <tr key={campaign.id}>
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                    {campaign.name}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {getAgentName(campaign.agent_id)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-900">
                    {campaign.channel_type}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <span className="inline-flex rounded-full bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-800">
                      {campaign.status}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {campaign.leads_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
