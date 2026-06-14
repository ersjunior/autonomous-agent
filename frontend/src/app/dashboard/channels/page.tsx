"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  createChannel,
  deleteChannel,
  fetchChannels,
  updateChannel,
} from "@/lib/api-entities";
import {
  credentialsToFormValues,
  mergeChannelCredentials,
} from "@/lib/credentials";
import { actionsFor } from "@/lib/protection";
import type { Channel, ChannelType } from "@/lib/types/channels";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

interface FieldConfig {
  name: string;
  label: string;
  type: "text" | "password";
  placeholder?: string;
}

const CHANNEL_TYPES: ChannelType[] = ["WHATSAPP", "TELEGRAM", "VOICE"];

const CHANNEL_FIELD_CONFIG: Record<ChannelType, FieldConfig[]> = {
  WHATSAPP: [
    { name: "account_sid", label: "Account SID", type: "text", placeholder: "ACxxxxxxxx" },
    { name: "auth_token", label: "Auth Token", type: "password" },
    { name: "phone_number", label: "Número de telefone", type: "text", placeholder: "+5511999999999" },
  ],
  TELEGRAM: [
    { name: "bot_token", label: "Bot Token", type: "password", placeholder: "123456:ABC-DEF..." },
  ],
  VOICE: [
    { name: "phone_numbers", label: "Números (separados por vírgula)", type: "text", placeholder: "+5511..., +5521..." },
    { name: "provider", label: "Provider", type: "text", placeholder: "twilio" },
  ],
};

type FormMode = "create" | "edit" | "view" | null;

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [selected, setSelected] = useState<Channel | null>(null);
  const [channelName, setChannelName] = useState("");
  const [channelType, setChannelType] = useState<ChannelType>("WHATSAPP");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Channel | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function loadChannels() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      setChannels(await fetchChannels());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar canais.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadChannels();
  }, []);

  function openCreate() {
    setSelected(null);
    setChannelName("");
    setChannelType("WHATSAPP");
    setCredentials({});
    setIsActive(true);
    setFormMode("create");
    setError("");
    setSuccess("");
  }

  function openChannel(agent: Channel, mode: "view" | "edit") {
    setSelected(agent);
    setChannelName(agent.name ?? "");
    setChannelType(agent.type);
    setIsActive(agent.is_active);
    setCredentials(
      credentialsToFormValues(agent.credentials, agent.type, mode === "view"),
    );
    setFormMode(mode);
    setError("");
    setSuccess("");
  }

  function closeForm() {
    setFormMode(null);
    setSelected(null);
  }

  function handleTypeChange(type: ChannelType) {
    setChannelType(type);
    setCredentials({});
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setSubmitting(true);

    const creds = mergeChannelCredentials(
      selected?.credentials ?? {},
      credentials,
      channelType,
    );

    const body: Record<string, unknown> = {
      type: channelType,
      credentials: creds,
      is_active: isActive,
    };
    const trimmedName = channelName.trim();
    if (trimmedName) {
      body.name = trimmedName;
    }

    try {
      if (formMode === "create") {
        await createChannel(body);
        setSuccess("Canal criado com sucesso.");
        setFormMode(null);
      } else if (formMode === "edit" && selected) {
        await updateChannel(selected.id, body);
        setSuccess("Canal atualizado com sucesso.");
        closeForm();
      }
      await loadChannels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar canal.");
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
      await deleteChannel(deleteTarget.id);
      setSuccess("Canal excluído.");
      setDeleteTarget(null);
      await loadChannels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir canal.");
    } finally {
      setDeleting(false);
    }
  }

  const readOnly = formMode === "view";
  const showInlineForm = formMode === "create";

  return (
    <>
      <PageHeader
        title="Canais"
        description="Configure WhatsApp, Telegram, voz e vídeo."
        actions={
          <button
            type="button"
            onClick={() => (showInlineForm ? closeForm() : openCreate())}
            className="btn-primary"
          >
            {showInlineForm ? "Cancelar" : "Adicionar canal"}
          </button>
        }
      />

      {error && <Alert>{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      {showInlineForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Novo canal</h2>
          <ChannelForm
            channelName={channelName}
            channelType={channelType}
            credentials={credentials}
            isActive={isActive}
            readOnly={false}
            onNameChange={setChannelName}
            onTypeChange={handleTypeChange}
            onFieldChange={(n, v) => setCredentials((p) => ({ ...p, [n]: v }))}
            onActiveChange={setIsActive}
            onSubmit={handleSubmit}
            submitting={submitting}
          />
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Carregando canais...</p>
      ) : channels.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhum canal cadastrado.
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted/50">
              <tr>
                {["Nome", "Tipo", "Status", "Criado em", "Ações"].map((col) => (
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
              {channels.map((channel) => {
                const actions = actionsFor(channel);
                return (
                  <tr key={channel.id} className="transition hover:bg-muted/30">
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-foreground">
                          {channel.name ?? "—"}
                        </span>
                        {channel.is_system && <SystemBadge />}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {channel.type}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <Badge variant={channel.is_active ? "success" : "muted"}>
                        {channel.is_active ? "Ativo" : "Inativo"}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                      {new Date(channel.created_at).toLocaleDateString("pt-BR")}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <RecordActionsBar
                        actions={actions}
                        onView={() => openChannel(channel, "view")}
                        onEdit={() => openChannel(channel, "edit")}
                        onDelete={() => setDeleteTarget(channel)}
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
        title={formMode === "view" ? "Visualizar canal" : "Editar canal"}
        onClose={closeForm}
      >
        <ChannelForm
          channelName={channelName}
          channelType={channelType}
          credentials={credentials}
          isActive={isActive}
          readOnly={readOnly}
          onNameChange={setChannelName}
          onTypeChange={handleTypeChange}
          onFieldChange={(n, v) => setCredentials((p) => ({ ...p, [n]: v }))}
          onActiveChange={setIsActive}
          onSubmit={handleSubmit}
          submitting={submitting}
          hideSubmit={readOnly}
        />
      </Modal>

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir canal"
        message={`Tem certeza que deseja excluir o canal "${deleteTarget?.name ?? deleteTarget?.type}"?`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function ChannelForm({
  channelName,
  channelType,
  credentials,
  isActive,
  readOnly,
  onNameChange,
  onTypeChange,
  onFieldChange,
  onActiveChange,
  onSubmit,
  submitting,
  hideSubmit = false,
}: {
  channelName: string;
  channelType: ChannelType;
  credentials: Record<string, string>;
  isActive: boolean;
  readOnly: boolean;
  onNameChange: (v: string) => void;
  onTypeChange: (t: ChannelType) => void;
  onFieldChange: (name: string, value: string) => void;
  onActiveChange: (v: boolean) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
  hideSubmit?: boolean;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label className="mb-2 block text-sm font-medium text-foreground">Nome</label>
        <input
          type="text"
          disabled={readOnly}
          value={channelName}
          onChange={(e) => onNameChange(e.target.value)}
          className="input-field disabled:opacity-70"
        />
      </div>

      <div>
        <label className="mb-2 block text-sm font-medium text-foreground">Tipo</label>
        <select
          disabled={readOnly}
          value={channelType}
          onChange={(e) => onTypeChange(e.target.value as ChannelType)}
          className="input-field disabled:opacity-70"
        >
          {CHANNEL_TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      {CHANNEL_FIELD_CONFIG[channelType].map((field) => (
        <div key={field.name}>
          <label className="mb-2 block text-sm font-medium text-foreground">{field.label}</label>
          <input
            type={readOnly && field.type === "password" ? "text" : field.type}
            required={!readOnly}
            disabled={readOnly}
            value={credentials[field.name] || ""}
            onChange={(e) => onFieldChange(field.name, e.target.value)}
            placeholder={field.placeholder}
            className="input-field disabled:opacity-70"
          />
        </div>
      ))}

      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          disabled={readOnly}
          checked={isActive}
          onChange={(e) => onActiveChange(e.target.checked)}
        />
        Canal ativo
      </label>

      {!hideSubmit && (
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Salvando..." : "Salvar canal"}
        </button>
      )}
    </form>
  );
}
