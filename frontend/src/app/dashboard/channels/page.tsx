"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

type ChannelType = "WHATSAPP" | "TELEGRAM" | "VOICE" | "VIDEO";

interface Channel {
  id: string;
  type: ChannelType;
  credentials: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

interface FieldConfig {
  name: string;
  label: string;
  type: "text" | "password";
  placeholder?: string;
}

const CHANNEL_TYPES: ChannelType[] = ["WHATSAPP", "TELEGRAM", "VOICE", "VIDEO"];

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
  VIDEO: [
    { name: "avatar_url", label: "Avatar URL", type: "text", placeholder: "https://..." },
    { name: "did_api_key", label: "D-ID API Key", type: "password" },
  ],
};

function buildCredentials(
  type: ChannelType,
  values: Record<string, string>
): Record<string, unknown> {
  if (type === "VOICE") {
    return {
      provider: values.provider || "twilio",
      phone_numbers: values.phone_numbers
        .split(",")
        .map((n) => n.trim())
        .filter(Boolean),
    };
  }
  return values;
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [channelType, setChannelType] = useState<ChannelType>("WHATSAPP");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function loadChannels() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      const res = await apiFetch("/api/v1/channels/");
      if (res.ok) {
        setChannels(await res.json());
      }
    } catch {
      setError("Erro ao carregar canais.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadChannels();
  }, []);

  function handleTypeChange(type: ChannelType) {
    setChannelType(type);
    setCredentials({});
  }

  function handleFieldChange(name: string, value: string) {
    setCredentials((prev) => ({ ...prev, [name]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const res = await apiFetch("/api/v1/channels/", {
        method: "POST",
        body: JSON.stringify({
          type: channelType,
          credentials: buildCredentials(channelType, credentials),
          is_active: true,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Erro ao criar canal.");
        return;
      }

      setShowForm(false);
      setCredentials({});
      setChannelType("WHATSAPP");
      await loadChannels();
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Canais"
        description="Configure WhatsApp, Telegram, voz e vídeo."
        actions={
          <button type="button" onClick={() => setShowForm(!showForm)} className="btn-primary">
            {showForm ? "Cancelar" : "Adicionar canal"}
          </button>
        }
      />

      {error && <Alert>{error}</Alert>}

      {showForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Novo canal</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="channelType" className="mb-2 block text-sm font-medium text-foreground">
                Tipo
              </label>
              <select
                id="channelType"
                value={channelType}
                onChange={(e) => handleTypeChange(e.target.value as ChannelType)}
                className="input-field"
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
                <label htmlFor={field.name} className="mb-2 block text-sm font-medium text-foreground">
                  {field.label}
                </label>
                <input
                  id={field.name}
                  type={field.type}
                  required
                  value={credentials[field.name] || ""}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  className="input-field"
                />
              </div>
            ))}

            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Salvando..." : "Salvar canal"}
            </button>
          </form>
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
                {["Tipo", "Status", "Criado em"].map((col) => (
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
              {channels.map((channel) => (
                <tr key={channel.id} className="transition hover:bg-muted/30">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-foreground">
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
