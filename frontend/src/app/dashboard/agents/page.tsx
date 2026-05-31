"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

type AgentMode = "ACTIVE" | "RECEPTIVE";

interface Agent {
  id: string;
  name: string;
  description?: string;
  mode: AgentMode;
  status: string;
  created_at: string;
}

const AGENT_MODES: AgentMode[] = ["ACTIVE", "RECEPTIVE"];

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<AgentMode>("RECEPTIVE");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function loadAgents() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      const res = await apiFetch("/api/v1/agents/");
      if (res.ok) {
        setAgents(await res.json());
      }
    } catch {
      setError("Erro ao carregar agentes.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAgents();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const res = await apiFetch("/api/v1/agents/", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: description || null,
          mode,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Erro ao criar agente.");
        return;
      }

      setShowForm(false);
      setName("");
      setDescription("");
      setMode("RECEPTIVE");
      await loadAgents();
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Agentes"
        description="Configure os agentes de IA do seu atendimento."
        actions={
          <button
            type="button"
            onClick={() => setShowForm(!showForm)}
            className="btn-primary"
          >
            {showForm ? "Cancelar" : "Novo agente"}
          </button>
        }
      />

      {error && <Alert>{error}</Alert>}

      {showForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Novo agente</h2>
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
              <label htmlFor="description" className="mb-2 block text-sm font-medium text-foreground">
                Descrição
              </label>
              <textarea
                id="description"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="input-field resize-none"
              />
            </div>

            <div>
              <label htmlFor="mode" className="mb-2 block text-sm font-medium text-foreground">
                Modo
              </label>
              <select
                id="mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as AgentMode)}
                className="input-field"
              >
                {AGENT_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Salvando..." : "Salvar agente"}
            </button>
          </form>
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Carregando agentes...</p>
      ) : agents.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhum agente cadastrado.
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted/50">
              <tr>
                {["Nome", "Modo", "Status", "Criado em"].map((col) => (
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
              {agents.map((agent) => (
                <tr key={agent.id} className="transition hover:bg-muted/30">
                  <td className="px-6 py-4 text-sm">
                    <p className="font-medium text-foreground">{agent.name}</p>
                    {agent.description && (
                      <p className="text-muted-foreground">{agent.description}</p>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                    {agent.mode}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <Badge>{agent.status}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                    {new Date(agent.created_at).toLocaleDateString("pt-BR")}
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
