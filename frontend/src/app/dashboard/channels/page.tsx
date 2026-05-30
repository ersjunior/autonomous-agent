"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

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
      window.location.href = "/login";
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
    <main className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Canais</h1>
          <p className="mt-1 text-gray-600">Configure os canais de comunicação.</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
        >
          {showForm ? "Cancelar" : "Adicionar Canal"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {showForm && (
        <div className="mb-8 rounded-lg bg-white p-6 shadow">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Novo canal</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="channelType" className="mb-1 block text-sm font-medium text-gray-700">
                Tipo
              </label>
              <select
                id="channelType"
                value={channelType}
                onChange={(e) => handleTypeChange(e.target.value as ChannelType)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                <label
                  htmlFor={field.name}
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  {field.label}
                </label>
                <input
                  id={field.name}
                  type={field.type}
                  required
                  value={credentials[field.name] || ""}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            ))}

            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "Salvando..." : "Salvar canal"}
            </button>
          </form>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Carregando canais...</p>
      ) : channels.length === 0 ? (
        <p className="text-gray-500">Nenhum canal cadastrado.</p>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Tipo
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Criado em
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {channels.map((channel) => (
                <tr key={channel.id}>
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                    {channel.type}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                        channel.is_active
                          ? "bg-green-100 text-green-800"
                          : "bg-gray-100 text-gray-800"
                      }`}
                    >
                      {channel.is_active ? "Ativo" : "Inativo"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {new Date(channel.created_at).toLocaleDateString("pt-BR")}
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
