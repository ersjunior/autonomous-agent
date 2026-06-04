"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  createAgent,
  deleteAgent,
  fetchAgents,
  updateAgent,
} from "@/lib/api-entities";
import { actionsFor } from "@/lib/protection";
import type { Agent, AgentMode } from "@/lib/types/agents";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

const AGENT_MODES: AgentMode[] = ["ACTIVE", "RECEPTIVE"];

type FormMode = "create" | "edit" | "view" | null;

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<AgentMode>("RECEPTIVE");
  const [configJson, setConfigJson] = useState("{}");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Agent | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function loadAgents() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      setAgents(await fetchAgents());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar agentes.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAgents();
  }, []);

  function openCreate() {
    setSelected(null);
    setName("");
    setDescription("");
    setMode("RECEPTIVE");
    setConfigJson("{}");
    setFormMode("create");
    setError("");
    setSuccess("");
  }

  function openView(agent: Agent) {
    setSelected(agent);
    setName(agent.name);
    setDescription(agent.description ?? "");
    setMode(agent.mode);
    setConfigJson(JSON.stringify(agent.config ?? {}, null, 2));
    setFormMode("view");
    setError("");
  }

  function openEdit(agent: Agent) {
    setSelected(agent);
    setName(agent.name);
    setDescription(agent.description ?? "");
    setMode(agent.mode);
    setConfigJson(JSON.stringify(agent.config ?? {}, null, 2));
    setFormMode("edit");
    setError("");
    setSuccess("");
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

    let config: Record<string, unknown> = {};
    try {
      config = configJson.trim() ? JSON.parse(configJson) : {};
    } catch {
      setError("Config inválido: use JSON válido.");
      setSubmitting(false);
      return;
    }

    try {
      if (formMode === "create") {
        await createAgent({
          name,
          description: description || null,
          mode,
          config,
        });
        setSuccess("Agente criado com sucesso.");
      } else if (formMode === "edit" && selected) {
        await updateAgent(selected.id, {
          name,
          description: description || null,
          mode,
          config,
        });
        setSuccess("Agente atualizado com sucesso.");
      }
      closeForm();
      await loadAgents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar agente.");
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
      await deleteAgent(deleteTarget.id);
      setSuccess("Agente excluído.");
      setDeleteTarget(null);
      await loadAgents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir agente.");
    } finally {
      setDeleting(false);
    }
  }

  const readOnly = formMode === "view";
  const showInlineForm = formMode === "create";

  return (
    <>
      <PageHeader
        title="Agentes"
        description="Configure os agentes de IA do seu atendimento."
        actions={
          <button type="button" onClick={openCreate} className="btn-primary">
            {showInlineForm ? "Cancelar" : "Novo agente"}
          </button>
        }
      />

      {error && <Alert variant="error">{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      {showInlineForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Novo agente</h2>
          <AgentFormFields
            name={name}
            description={description}
            mode={mode}
            configJson={configJson}
            readOnly={false}
            onNameChange={setName}
            onDescriptionChange={setDescription}
            onModeChange={setMode}
            onConfigChange={setConfigJson}
            onSubmit={handleSubmit}
            submitting={submitting}
            submitLabel="Salvar agente"
          />
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
                {["Nome", "Modo", "Status", "Criado em", "Ações"].map((col) => (
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
              {agents.map((agent) => {
                const actions = actionsFor(agent);
                return (
                  <tr key={agent.id} className="transition hover:bg-muted/30">
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-foreground">{agent.name}</p>
                        {agent.is_system && <SystemBadge />}
                      </div>
                      {agent.description && (
                        <p className="mt-1 line-clamp-2 text-muted-foreground">
                          {agent.description}
                        </p>
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
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <RecordActionsBar
                        actions={actions}
                        onView={() => openView(agent)}
                        onEdit={() => openEdit(agent)}
                        onDelete={() => setDeleteTarget(agent)}
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
        title={
          formMode === "view"
            ? "Visualizar agente"
            : formMode === "edit"
              ? "Editar agente"
              : ""
        }
        onClose={closeForm}
        wide={formMode === "view"}
      >
        <AgentFormFields
          name={name}
          description={description}
          mode={mode}
          configJson={configJson}
          readOnly={readOnly}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onModeChange={setMode}
          onConfigChange={setConfigJson}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitLabel="Salvar alterações"
          hideSubmit={readOnly}
        />
      </Modal>

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir agente"
        message={`Tem certeza que deseja excluir o agente "${deleteTarget?.name}"? Esta ação não pode ser desfeita.`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function AgentFormFields({
  name,
  description,
  mode,
  configJson,
  readOnly,
  onNameChange,
  onDescriptionChange,
  onModeChange,
  onConfigChange,
  onSubmit,
  submitting,
  submitLabel,
  hideSubmit = false,
}: {
  name: string;
  description: string;
  mode: AgentMode;
  configJson: string;
  readOnly: boolean;
  onNameChange: (v: string) => void;
  onDescriptionChange: (v: string) => void;
  onModeChange: (v: AgentMode) => void;
  onConfigChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
  submitLabel: string;
  hideSubmit?: boolean;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="agentName" className="mb-2 block text-sm font-medium text-foreground">
          Nome
        </label>
        <input
          id="agentName"
          type="text"
          required
          disabled={readOnly}
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          className="input-field disabled:opacity-70"
        />
      </div>

      <div>
        <label htmlFor="agentDesc" className="mb-2 block text-sm font-medium text-foreground">
          Descrição
        </label>
        <textarea
          id="agentDesc"
          rows={readOnly ? 6 : 3}
          disabled={readOnly}
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          className="input-field resize-none disabled:opacity-70"
        />
      </div>

      <div>
        <label htmlFor="agentMode" className="mb-2 block text-sm font-medium text-foreground">
          Modo
        </label>
        <select
          id="agentMode"
          disabled={readOnly}
          value={mode}
          onChange={(e) => onModeChange(e.target.value as AgentMode)}
          className="input-field disabled:opacity-70"
        >
          {AGENT_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="agentConfig" className="mb-2 block text-sm font-medium text-foreground">
          Config (JSON)
        </label>
        <textarea
          id="agentConfig"
          rows={4}
          disabled={readOnly}
          value={configJson}
          onChange={(e) => onConfigChange(e.target.value)}
          className="input-field resize-none font-mono text-xs disabled:opacity-70"
        />
      </div>

      {!hideSubmit && (
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Salvando..." : submitLabel}
        </button>
      )}
    </form>
  );
}
