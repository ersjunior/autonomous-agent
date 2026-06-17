"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  createAgent,
  deleteAgent,
  fetchAgents,
  updateAgent,
  updateAgentIdentity,
} from "@/lib/api-entities";
import { agentActionsFor } from "@/lib/protection";
import type { Agent, AgentMode } from "@/lib/types/agents";
import {
  configWithoutIdentity,
  formValuesToIdentityUpdate,
  identityFromAgentConfig,
  identityToFormValues,
} from "@/lib/types/identity";
import type { InstitutionalIdentity } from "@/lib/types/identity";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

const AGENT_MODES: AgentMode[] = ["ACTIVE", "RECEPTIVE"];

type FormMode = "create" | "edit" | "view" | null;

function populateAgentForm(agent: Agent | null) {
  const config = agent?.config ?? {};
  return {
    name: agent?.name ?? "",
    description: agent?.description ?? "",
    mode: agent?.mode ?? ("RECEPTIVE" as AgentMode),
    identityValues: identityToFormValues(identityFromAgentConfig(config)),
    configJson: JSON.stringify(configWithoutIdentity(config), null, 2),
  };
}

function identityPatchFromForm(
  values: Record<keyof InstitutionalIdentity, string>
): ReturnType<typeof formValuesToIdentityUpdate> {
  return formValuesToIdentityUpdate(values);
}

function buildConfigWithIdentity(
  configJson: string,
  identityValues: Record<keyof InstitutionalIdentity, string>
): Record<string, unknown> | null {
  let config: Record<string, unknown> = {};
  try {
    config = configJson.trim() ? JSON.parse(configJson) : {};
  } catch {
    return null;
  }
  return mergeIdentityIntoConfig(config, identityPatchFromForm(identityValues));
}

function mergeIdentityIntoConfig(
  config: Record<string, unknown>,
  identityPayload: ReturnType<typeof formValuesToIdentityUpdate>
): Record<string, unknown> {
  const merged = { ...config };
  const identity: Record<string, string> = {};
  for (const [key, value] of Object.entries(identityPayload)) {
    if (value != null) {
      identity[key] = value;
    }
  }
  if (Object.keys(identity).length > 0) {
    merged.identity = identity;
  } else {
    delete merged.identity;
  }
  return merged;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<AgentMode>("RECEPTIVE");
  const [identityValues, setIdentityValues] = useState(
    identityToFormValues(null)
  );
  const [configJson, setConfigJson] = useState("{}");
  const [advancedConfigOpen, setAdvancedConfigOpen] = useState(false);
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
    const form = populateAgentForm(null);
    setName(form.name);
    setDescription(form.description);
    setMode(form.mode);
    setIdentityValues(form.identityValues);
    setConfigJson(form.configJson);
    setAdvancedConfigOpen(false);
    setFormMode("create");
    setError("");
    setSuccess("");
  }

  function openView(agent: Agent) {
    setSelected(agent);
    const form = populateAgentForm(agent);
    setName(form.name);
    setDescription(form.description);
    setMode(form.mode);
    setIdentityValues(form.identityValues);
    setConfigJson(form.configJson);
    setAdvancedConfigOpen(false);
    setFormMode("view");
    setError("");
  }

  function openEdit(agent: Agent) {
    setSelected(agent);
    const form = populateAgentForm(agent);
    setName(form.name);
    setDescription(form.description);
    setMode(form.mode);
    setIdentityValues(form.identityValues);
    setConfigJson(form.configJson);
    setAdvancedConfigOpen(false);
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

    let operationalConfig: Record<string, unknown> = {};
    try {
      operationalConfig = configJson.trim() ? JSON.parse(configJson) : {};
    } catch {
      setError("Config inválido: use JSON válido.");
      setSubmitting(false);
      return;
    }

    const identityPayload = identityPatchFromForm(identityValues);
    const isSystemAgent = Boolean(selected?.is_system);

    try {
      if (formMode === "create") {
        const config = buildConfigWithIdentity(configJson, identityValues);
        if (!config) {
          setError("Config inválido: use JSON válido.");
          setSubmitting(false);
          return;
        }
        await createAgent({
          name,
          description: description || null,
          mode,
          config,
        });
        setSuccess("Agente criado com sucesso.");
      } else if (formMode === "edit" && selected) {
        await updateAgentIdentity(selected.id, identityPayload);
        if (!isSystemAgent) {
          await updateAgent(selected.id, {
            name,
            description: description || null,
            mode,
            config: mergeIdentityIntoConfig(operationalConfig, identityPayload),
          });
          setSuccess("Agente atualizado com sucesso.");
        } else {
          setSuccess("Identidade do agente salva com sucesso.");
        }
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
  const isSystemAgent = Boolean(selected?.is_system);
  const coreFieldsReadOnly = readOnly || isSystemAgent;
  const identityEditable = !readOnly;
  const configJsonReadOnly = readOnly || isSystemAgent;
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
            identityValues={identityValues}
            configJson={configJson}
            advancedConfigOpen={advancedConfigOpen}
            coreFieldsReadOnly={false}
            identityEditable
            configJsonReadOnly={false}
            onNameChange={setName}
            onDescriptionChange={setDescription}
            onModeChange={setMode}
            onIdentityChange={(key, value) =>
              setIdentityValues((prev) => ({ ...prev, [key]: value }))
            }
            onConfigChange={setConfigJson}
            onAdvancedConfigToggle={() => setAdvancedConfigOpen((v) => !v)}
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
                const actions = agentActionsFor(agent);
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
            : formMode === "edit" && isSystemAgent
              ? "Editar identidade do agente"
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
          identityValues={identityValues}
          configJson={configJson}
          advancedConfigOpen={advancedConfigOpen}
          coreFieldsReadOnly={coreFieldsReadOnly}
          identityEditable={identityEditable}
          configJsonReadOnly={configJsonReadOnly}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onModeChange={setMode}
          onIdentityChange={(key, value) =>
            setIdentityValues((prev) => ({ ...prev, [key]: value }))
          }
          onConfigChange={setConfigJson}
          onAdvancedConfigToggle={() => setAdvancedConfigOpen((v) => !v)}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitLabel={
            isSystemAgent && formMode === "edit"
              ? "Salvar identidade"
              : "Salvar alterações"
          }
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
  identityValues,
  configJson,
  advancedConfigOpen,
  coreFieldsReadOnly,
  identityEditable,
  configJsonReadOnly,
  onNameChange,
  onDescriptionChange,
  onModeChange,
  onIdentityChange,
  onConfigChange,
  onAdvancedConfigToggle,
  onSubmit,
  submitting,
  submitLabel,
  hideSubmit = false,
}: {
  name: string;
  description: string;
  mode: AgentMode;
  identityValues: Record<keyof InstitutionalIdentity, string>;
  configJson: string;
  advancedConfigOpen: boolean;
  coreFieldsReadOnly: boolean;
  identityEditable: boolean;
  configJsonReadOnly: boolean;
  onNameChange: (v: string) => void;
  onDescriptionChange: (v: string) => void;
  onModeChange: (v: AgentMode) => void;
  onIdentityChange: (key: keyof InstitutionalIdentity, value: string) => void;
  onConfigChange: (v: string) => void;
  onAdvancedConfigToggle: () => void;
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
          disabled={coreFieldsReadOnly}
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
          rows={coreFieldsReadOnly ? 6 : 3}
          disabled={coreFieldsReadOnly}
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
          disabled={coreFieldsReadOnly}
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

      <div className="glass-card space-y-4 p-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Identidade (override)</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Deixe vazio para herdar da Identidade da empresa (Configurações). Preencha só o que
            este agente deve sobrescrever.
          </p>
        </div>

        <div>
          <label
            htmlFor="agentCompanyName"
            className="mb-2 block text-sm font-medium text-foreground"
          >
            Nome da empresa
          </label>
          <input
            id="agentCompanyName"
            type="text"
            disabled={!identityEditable}
            value={identityValues.company_name}
            onChange={(e) => onIdentityChange("company_name", e.target.value)}
            className="input-field disabled:opacity-70"
          />
        </div>

        <div>
          <label
            htmlFor="agentDisplayName"
            className="mb-2 block text-sm font-medium text-foreground"
          >
            Nome de exibição
          </label>
          <input
            id="agentDisplayName"
            type="text"
            disabled={!identityEditable}
            value={identityValues.display_name}
            onChange={(e) => onIdentityChange("display_name", e.target.value)}
            className="input-field disabled:opacity-70"
          />
        </div>

        <div>
          <label htmlFor="agentTone" className="mb-2 block text-sm font-medium text-foreground">
            Tom
          </label>
          <input
            id="agentTone"
            type="text"
            disabled={!identityEditable}
            value={identityValues.tone}
            onChange={(e) => onIdentityChange("tone", e.target.value)}
            placeholder="Ex.: formal e acolhedor"
            className="input-field disabled:opacity-70"
          />
        </div>

        <div>
          <label
            htmlFor="agentBusinessContext"
            className="mb-2 block text-sm font-medium text-foreground"
          >
            Contexto do negócio
          </label>
          <textarea
            id="agentBusinessContext"
            rows={4}
            disabled={!identityEditable}
            value={identityValues.business_context}
            maxLength={4000}
            onChange={(e) => onIdentityChange("business_context", e.target.value)}
            className="input-field resize-y disabled:opacity-70"
          />
        </div>

        <div>
          <label
            htmlFor="agentGreetingHint"
            className="mb-2 block text-sm font-medium text-foreground"
          >
            Dica de saudação
          </label>
          <input
            id="agentGreetingHint"
            type="text"
            disabled={!identityEditable}
            value={identityValues.greeting_hint}
            onChange={(e) => onIdentityChange("greeting_hint", e.target.value)}
            placeholder="Ex.: Cumprimente pelo nome quando souber"
            className="input-field disabled:opacity-70"
          />
        </div>
      </div>

      <div>
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left text-sm font-medium text-foreground"
          onClick={onAdvancedConfigToggle}
        >
          {advancedConfigOpen ? (
            <ChevronDown className="h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0" />
          )}
          JSON avançado (config)
        </button>
        {advancedConfigOpen && (
          <div className="mt-2">
            <textarea
              id="agentConfig"
              rows={6}
              disabled={configJsonReadOnly}
              value={configJson}
              onChange={(e) => onConfigChange(e.target.value)}
              className="input-field resize-none font-mono text-xs disabled:opacity-70"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Config operacional (tipo, etc.). A identidade é editada na seção acima.
            </p>
          </div>
        )}
      </div>

      {!hideSubmit && (
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Salvando..." : submitLabel}
        </button>
      )}
    </form>
  );
}
