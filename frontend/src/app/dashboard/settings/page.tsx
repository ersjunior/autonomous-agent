"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import {
  fetchAudioBlob,
  fetchVoiceSampleAudio,
  formatApiError,
  getSettings,
  getVoiceSampleInfo,
  getWorkspaceIdentity,
  testVoice,
  updateSettings,
  updateWorkspaceIdentity,
  uploadVoiceSample,
} from "@/lib/api";
import { fetchTunnelStatus } from "@/lib/api-tunnel";
import type {
  SettingCategory,
  SettingField,
  SettingsResponse,
  VoiceSampleInfo,
  VoiceSampleUploadResponse,
  VoiceTestResponse,
} from "@/lib/types/settings";
import type { InstitutionalIdentity } from "@/lib/types/identity";
import {
  formValuesToIdentityUpdate,
  identityToFormValues,
} from "@/lib/types/identity";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { CopyButton } from "@/components/ui/CopyButton";
import { PageHeader } from "@/components/ui/PageHeader";
import type { TunnelStatusLevel, TunnelStatusResponse } from "@/lib/types/tunnel";

const SECRET_MASK = "********";
const DEFAULT_TEST_TEXT =
  "Olá! Esta é uma demonstração da minha voz personalizada, falando em português.";
const TUNNEL_POLL_MS = 10_000;
const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION;

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function formatModifiedAt(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  try {
    return new Date(iso).toLocaleString("pt-BR");
  } catch {
    return iso;
  }
}

function revokeBlobUrl(ref: MutableRefObject<string | null>) {
  if (ref.current) {
    URL.revokeObjectURL(ref.current);
    ref.current = null;
  }
}

const LLM_CATEGORIES = new Set(["llm", "system"]);
const AGENT_CATEGORIES = new Set(["agent"]);
const AUDIO_CATEGORIES = new Set(["stt", "tts"]);

type TabId = "llm" | "agent" | "identity" | "audio" | "tunnel";

const TUNNEL_STATUS_LABELS: Record<TunnelStatusLevel, string> = {
  aguardando: "Aguardando URL pública",
  configurado: "URL configurada (não verificada)",
  verificado: "Túnel verificado",
  inacessivel: "URL configurada, mas inacessível",
};

function tunnelStatusBadgeVariant(
  status: TunnelStatusLevel,
): "default" | "success" | "warning" | "muted" {
  if (status === "verificado") {
    return "success";
  }
  if (status === "inacessivel") {
    return "warning";
  }
  if (status === "configurado") {
    return "default";
  }
  return "muted";
}

function publicBaseUrlSourceLabel(source: TunnelStatusResponse["public_base_url_source"]): string {
  if (source === "env") {
    return ".env (PUBLIC_BASE_URL)";
  }
  if (source === "tunnel_file") {
    return "arquivo do túnel (tunnel_url.txt)";
  }
  return "—";
}

function formatTunnelLastVerified(date: Date): string {
  return date.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function isMaskedSecret(value: string): boolean {
  if (!value.trim()) {
    return true;
  }
  if (value === SECRET_MASK) {
    return true;
  }
  return value.includes("...");
}

function providerPrefix(key: string, provider: string | null | undefined): boolean {
  if (!provider) {
    return false;
  }
  const p = provider.toLowerCase();
  if (p === "openai" && key.startsWith("openai_")) {
    return true;
  }
  if (p === "ollama" && key.startsWith("ollama_")) {
    return true;
  }
  if (p === "faster_whisper" && key.startsWith("whisper_")) {
    return true;
  }
  if (p === "elevenlabs" && key.startsWith("elevenlabs_")) {
    return true;
  }
  if (p === "coqui" && key.startsWith("coqui_")) {
    return true;
  }
  return false;
}

function SettingFieldInput({
  field,
  value,
  onChange,
  highlighted,
  onRestoreDefault,
}: {
  field: SettingField;
  value: string;
  onChange: (key: string, value: string) => void;
  highlighted: boolean;
  onRestoreDefault?: () => void;
}) {
  const inputClass = `input-field ${highlighted ? "ring-1 ring-primary/50" : ""}`;

  if (field.read_only) {
    return (
      <div>
        <input
          type="text"
          className={`${inputClass} cursor-not-allowed opacity-70`}
          value={value}
          disabled
          title="Alterar exige migração do banco (reindex de embeddings). Valor definido no .env."
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Somente leitura — mudanças exigem migração do banco de dados.
        </p>
      </div>
    );
  }

  if (field.type === "enum" && field.options) {
    return (
      <select
        className={inputClass}
        value={value}
        onChange={(e) => onChange(field.key, e.target.value)}
      >
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }

  if (field.is_secret || field.type === "secret") {
    return (
      <input
        type="password"
        className={inputClass}
        value={value}
        placeholder={isMaskedSecret(value) ? "•••••••• (deixe em branco para manter)" : ""}
        onChange={(e) => onChange(field.key, e.target.value)}
        autoComplete="off"
      />
    );
  }

  if (field.type === "number") {
    return (
      <input
        type="number"
        className={inputClass}
        value={value}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        step={field.step ?? undefined}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
    );
  }

  if (field.type === "textarea") {
    const maxLen = field.max_length ?? 4000;
    return (
      <div className="space-y-2">
        <textarea
          className={`${inputClass} min-h-[160px] resize-y`}
          value={value}
          maxLength={maxLen}
          onChange={(e) => onChange(field.key, e.target.value)}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            {value.length} / {maxLen} caracteres
          </span>
          {field.default_value && onRestoreDefault && (
            <button
              type="button"
              className="text-primary hover:underline"
              onClick={onRestoreDefault}
            >
              Restaurar padrão
            </button>
          )}
        </div>
      </div>
    );
  }

  const placeholder =
    field.key === "human_handoff_whatsapp"
      ? "+55 11 99999-9999 (E.164 ou DDD+número)"
      : undefined;

  return (
    <input
      type="text"
      className={inputClass}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(field.key, e.target.value)}
    />
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>("llm");
  const [categories, setCategories] = useState<SettingCategory[]>([]);
  const [runtime, setRuntime] = useState<Record<string, string | number | null>>({});
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [initialValues, setInitialValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [wavFile, setWavFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sampleInfo, setSampleInfo] = useState<VoiceSampleInfo | null>(null);
  const [loadingSample, setLoadingSample] = useState(false);
  const [referencePlayUrl, setReferencePlayUrl] = useState<string | null>(null);
  const referenceObjectUrl = useRef<string | null>(null);

  const [testText, setTestText] = useState(DEFAULT_TEST_TEXT);
  const [testingVoice, setTestingVoice] = useState(false);
  const [testPlayUrl, setTestPlayUrl] = useState<string | null>(null);
  const testObjectUrl = useRef<string | null>(null);

  const [tunnelStatus, setTunnelStatus] = useState<TunnelStatusResponse | null>(null);
  const [tunnelLoading, setTunnelLoading] = useState(false);
  const [tunnelRefreshing, setTunnelRefreshing] = useState(false);
  const [tunnelLastVerifiedAt, setTunnelLastVerifiedAt] = useState<Date | null>(null);
  const [tunnelError, setTunnelError] = useState("");
  const tunnelFetchingRef = useRef(false);
  const tunnelStatusRef = useRef<TunnelStatusResponse | null>(null);

  const [identityValues, setIdentityValues] = useState(identityToFormValues(null));
  const [identityLoading, setIdentityLoading] = useState(false);
  const [identitySaving, setIdentitySaving] = useState(false);

  const loadTunnelStatus = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (tunnelFetchingRef.current) {
      return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    const isInitial = mode === "initial";
    tunnelFetchingRef.current = true;

    if (isInitial) {
      setTunnelLoading(true);
      setTunnelError("");
    } else {
      setTunnelRefreshing(true);
    }

    try {
      const data = await fetchTunnelStatus();
      setTunnelStatus(data);
      tunnelStatusRef.current = data;
      setTunnelLastVerifiedAt(new Date());
    } catch (err) {
      if (isInitial) {
        setTunnelError(err instanceof Error ? err.message : "Erro ao carregar status do túnel.");
        setTunnelStatus(null);
        tunnelStatusRef.current = null;
      }
    } finally {
      tunnelFetchingRef.current = false;
      if (isInitial) {
        setTunnelLoading(false);
      } else {
        setTunnelRefreshing(false);
      }
    }
  }, []);

  const loadIdentity = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setIdentityLoading(true);
    setError("");
    try {
      const res = await getWorkspaceIdentity();
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao carregar identidade da empresa"));
        }
        return;
      }

      const data: InstitutionalIdentity = await res.json();
      const values = identityToFormValues(data);
      setIdentityValues(values);
    } catch {
      setError("Erro de conexão ao carregar identidade da empresa.");
    } finally {
      setIdentityLoading(false);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setLoading(true);
    setError("");
    try {
      const res = await getSettings();
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao carregar configurações"));
        }
        return;
      }

      const data: SettingsResponse = await res.json();
      setCategories(data.categories);
      setRuntime(data.runtime ?? {});

      const values: Record<string, string> = {};
      for (const cat of data.categories) {
        for (const field of cat.fields) {
          values[field.key] = formatValue(field.value);
        }
      }
      setFormValues(values);
      setInitialValues(values);
    } catch {
      setError("Erro de conexão ao carregar configurações.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReferencePlayer = useCallback(async () => {
    revokeBlobUrl(referenceObjectUrl);
    setReferencePlayUrl(null);
    try {
      const blob = await fetchVoiceSampleAudio();
      const url = URL.createObjectURL(blob);
      referenceObjectUrl.current = url;
      setReferencePlayUrl(url);
    } catch {
      setError("Erro ao carregar áudio da amostra de referência.");
    }
  }, []);

  const loadVoiceSampleInfo = useCallback(async () => {
    setLoadingSample(true);
    try {
      const res = await getVoiceSampleInfo();
      if (!res.ok) {
        setSampleInfo(null);
        return;
      }
      const info: VoiceSampleInfo = await res.json();
      setSampleInfo(info);
      if (info.exists) {
        await loadReferencePlayer();
      } else {
        revokeBlobUrl(referenceObjectUrl);
        setReferencePlayUrl(null);
      }
    } catch {
      setSampleInfo(null);
    } finally {
      setLoadingSample(false);
    }
  }, [loadReferencePlayer]);

  useEffect(() => {
    loadSettings();
    return () => {
      revokeBlobUrl(referenceObjectUrl);
      revokeBlobUrl(testObjectUrl);
    };
  }, [loadSettings]);

  useEffect(() => {
    if (activeTab === "audio" && !loading) {
      loadVoiceSampleInfo();
    }
  }, [activeTab, loading, loadVoiceSampleInfo]);

  useEffect(() => {
    if (activeTab !== "tunnel") {
      return;
    }

    void loadTunnelStatus(tunnelStatusRef.current ? "refresh" : "initial");

    const timer = setInterval(() => {
      void loadTunnelStatus("refresh");
    }, TUNNEL_POLL_MS);

    return () => clearInterval(timer);
  }, [activeTab, loadTunnelStatus]);

  useEffect(() => {
    if (activeTab === "identity") {
      void loadIdentity();
    }
  }, [activeTab, loadIdentity]);

  const visibleCategories = useMemo(() => {
    const allowed =
      activeTab === "llm"
        ? LLM_CATEGORIES
        : activeTab === "agent"
          ? AGENT_CATEGORIES
          : AUDIO_CATEGORIES;
    return categories.filter((c) => allowed.has(c.id));
  }, [categories, activeTab]);

  const activeLlm = formatValue(runtime.llm_provider);
  const activeStt = formatValue(runtime.stt_provider);
  const activeTts = formatValue(runtime.tts_provider);

  function handleFieldChange(key: string, value: string) {
    setFormValues((prev) => ({ ...prev, [key]: value }));
    setSuccess("");
  }

  function buildDirtyChanges(): Record<string, string | null> {
    const changes: Record<string, string | null> = {};

    for (const cat of categories) {
      for (const field of cat.fields) {
        if (field.read_only) {
          continue;
        }
        const current = formValues[field.key] ?? "";
        const initial = initialValues[field.key] ?? "";
        if (current === initial) {
          continue;
        }
        if (field.is_secret && isMaskedSecret(current)) {
          continue;
        }
        changes[field.key] = current.trim() || null;
      }
    }

    return changes;
  }

  async function handleSaveIdentity(e: FormEvent) {
    e.preventDefault();
    setIdentitySaving(true);
    setError("");
    setSuccess("");
    try {
      const payload = formValuesToIdentityUpdate(identityValues);
      const res = await updateWorkspaceIdentity(payload);
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao salvar identidade da empresa"));
        }
        return;
      }

      const data: InstitutionalIdentity = await res.json();
      const values = identityToFormValues(data);
      setIdentityValues(values);
      setSuccess("Identidade da empresa salva com sucesso.");
    } catch {
      setError("Erro de conexão ao salvar identidade da empresa.");
    } finally {
      setIdentitySaving(false);
    }
  }

  function handleIdentityFieldChange(key: keyof typeof identityValues, value: string) {
    setIdentityValues((prev) => ({ ...prev, [key]: value }));
    setSuccess("");
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    const changes = buildDirtyChanges();
    if (Object.keys(changes).length === 0) {
      setError("Nenhuma alteração para salvar.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await updateSettings(changes);
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao salvar configurações"));
        }
        return;
      }

      const data: SettingsResponse = await res.json();
      setCategories(data.categories);
      setRuntime(data.runtime ?? {});

      const values: Record<string, string> = {};
      for (const cat of data.categories) {
        for (const field of cat.fields) {
          values[field.key] = formatValue(field.value);
        }
      }
      setFormValues(values);
      setInitialValues(values);
      setSuccess("Configurações salvas e aplicadas sem reiniciar os containers.");
    } catch {
      setError("Erro de conexão ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  async function handleUploadSample() {
    if (!wavFile) {
      setError("Selecione um arquivo .wav.");
      return;
    }

    setUploading(true);
    setError("");
    try {
      const res = await uploadVoiceSample(wavFile);
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao enviar amostra"));
        }
        return;
      }

      const data: VoiceSampleUploadResponse = await res.json();
      setSuccess(
        `${data.message} (${formatBytes(data.size_bytes)}) — caminho ${data.path}`
      );
      setWavFile(null);
      await loadSettings();
      await loadVoiceSampleInfo();
    } catch {
      setError("Erro de conexão no upload.");
    } finally {
      setUploading(false);
    }
  }

  async function handleVoiceTest() {
    setTestingVoice(true);
    setError("");
    revokeBlobUrl(testObjectUrl);
    setTestPlayUrl(null);

    try {
      const res = await testVoice(testText);

      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro no teste de voz"));
        }
        return;
      }

      const data: VoiceTestResponse = await res.json();
      const blob = await fetchAudioBlob(data.audio_url);
      const url = URL.createObjectURL(blob);
      testObjectUrl.current = url;
      setTestPlayUrl(url);
      setSuccess("Áudio de teste gerado com sucesso.");
    } catch (err) {
      if (err instanceof Error && err.message.includes("carregar áudio")) {
        setError(err.message);
      } else {
        setError("Erro de conexão no teste de voz.");
      }
    } finally {
      setTestingVoice(false);
    }
  }

  function renderCategoryFields(cat: SettingCategory, providerKey: string | null) {
    return (
      <div key={cat.id} className="space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {cat.label}
        </h3>
        {cat.fields.map((field) => {
          const highlighted = providerPrefix(field.key, providerKey);
          return (
            <div key={field.key}>
              <label
                htmlFor={field.key}
                className="mb-2 block text-sm font-medium text-foreground"
              >
                {field.label}
              </label>
              <SettingFieldInput
                field={field}
                value={formValues[field.key] ?? ""}
                onChange={handleFieldChange}
                highlighted={highlighted}
                onRestoreDefault={
                  field.default_value
                    ? () => handleFieldChange(field.key, field.default_value ?? "")
                    : undefined
                }
              />
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Configurações"
        description="Provedores, comportamento do agente e áudio. Alterações aplicam em tempo real."
        actions={
          <span className="text-xs text-muted-foreground">
            versão {APP_VERSION}
          </span>
        }
      />

      {error && <Alert>{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      <div className="mb-6 flex flex-wrap gap-2 border-b border-border">
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "llm"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("llm")}
        >
          Texto (LLM)
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "agent"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("agent")}
        >
          Comportamento
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "identity"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("identity")}
        >
          Identidade da empresa
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "audio"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("audio")}
        >
          Áudio (STT/TTS)
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "tunnel"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("tunnel")}
        >
          Túnel & Webhooks
        </button>
      </div>

      {activeTab === "tunnel" ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              URL pública, modos e webhooks para colar no Twilio/Telegram. Somente leitura —
              não configura provedores automaticamente.
              {tunnelLastVerifiedAt && (
                <span className="mt-1 block text-xs">
                  Última atualização: {formatTunnelLastVerified(tunnelLastVerifiedAt)}
                  {tunnelRefreshing ? " · atualizando…" : ""}
                </span>
              )}
            </p>
            <button
              type="button"
              className="btn-secondary"
              disabled={tunnelLoading || tunnelRefreshing}
              onClick={() =>
                void loadTunnelStatus(tunnelStatus ? "refresh" : "initial")
              }
            >
              {tunnelLoading || tunnelRefreshing ? "Atualizando..." : "Atualizar"}
            </button>
          </div>

          {tunnelError && <Alert>{tunnelError}</Alert>}

          {tunnelLoading && !tunnelStatus ? (
            <p className="text-sm text-muted-foreground">Carregando status do túnel...</p>
          ) : tunnelStatus ? (
            <>
              <div className="glass-card space-y-4 p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">Status:</span>
                  <Badge variant={tunnelStatusBadgeVariant(tunnelStatus.status)}>
                    {TUNNEL_STATUS_LABELS[tunnelStatus.status]}
                  </Badge>
                </div>
                {tunnelStatus.status !== "verificado" && (
                  <p className="text-xs text-muted-foreground">
                    A URL pública ainda não foi confirmada como alcançável (health probe em{" "}
                    <code className="text-foreground">/health</code>).
                  </p>
                )}
                {tunnelStatus.health_probe.attempted && (
                  <p className="text-xs text-muted-foreground">
                    Última verificação: HTTP {tunnelStatus.health_probe.status_code ?? "—"}
                    {tunnelStatus.health_probe.latency_ms != null
                      ? ` · ${tunnelStatus.health_probe.latency_ms} ms`
                      : ""}
                    {tunnelStatus.health_probe.error
                      ? ` · ${tunnelStatus.health_probe.error}`
                      : ""}
                  </p>
                )}
              </div>

              {tunnelStatus.env_tunnel_url_diverges && (
                <Alert variant="warning">
                  A URL no <code>.env</code> pode estar desatualizada; o túnel gerou outra (
                  <span className="font-mono text-xs">
                    {tunnelStatus.tunnel_url_file_raw}
                  </span>
                  ). Remova ou atualize <code>PUBLIC_BASE_URL</code> no <code>.env</code> para
                  usar a URL do quick tunnel.
                </Alert>
              )}

              <div className="glass-card space-y-4 p-6">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  URL pública
                </h3>
                <div className="space-y-3 text-sm">
                  <div>
                    <span className="text-muted-foreground">Resolvida: </span>
                    <code className="break-all text-foreground">
                      {tunnelStatus.public_base_url_resolved ?? "—"}
                    </code>
                    {tunnelStatus.public_base_url_resolved && (
                      <div className="mt-2">
                        <CopyButton text={tunnelStatus.public_base_url_resolved} />
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-muted-foreground">Modo do túnel:</span>
                    <Badge>{tunnelStatus.tunnel_mode}</Badge>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Fonte: </span>
                    {publicBaseUrlSourceLabel(tunnelStatus.public_base_url_source)}
                  </div>
                  {tunnelStatus.public_base_url_env && (
                    <div>
                      <span className="text-muted-foreground">PUBLIC_BASE_URL no .env: </span>
                      <code className="break-all">{tunnelStatus.public_base_url_env}</code>
                    </div>
                  )}
                  {tunnelStatus.tunnel_mode === "temporary" && (
                    <div>
                      <span className="text-muted-foreground">Arquivo do túnel: </span>
                      {tunnelStatus.tunnel_url_file_exists
                        ? `encontrado (${tunnelStatus.tunnel_url_file})`
                        : `aguardando cloudflared gravar em ${tunnelStatus.tunnel_url_file}`}
                      {tunnelStatus.tunnel_url_file_raw && (
                        <div className="mt-1 font-mono text-xs text-muted-foreground">
                          Conteúdo: {tunnelStatus.tunnel_url_file_raw}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="glass-card space-y-4 p-6">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Modo Telegram
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{tunnelStatus.telegram_mode}</Badge>
                </div>
                {tunnelStatus.telegram_mode === "polling" ? (
                  <Alert variant="info">
                    Inbound via <code>getUpdates</code> — inicie o serviço{" "}
                    <code>telegram-polling</code> (profile Docker{" "}
                    <code>--profile telegram-polling</code>). Não use webhook do Telegram neste
                    modo.
                  </Alert>
                ) : (
                  <div className="space-y-3 text-sm">
                    {tunnelStatus.telegram_webhook_url ? (
                      <>
                        <div>
                          <span className="text-muted-foreground">Webhook Telegram: </span>
                          <code className="break-all">{tunnelStatus.telegram_webhook_url}</code>
                        </div>
                        <CopyButton text={tunnelStatus.telegram_webhook_url} />
                      </>
                    ) : (
                      <p className="text-muted-foreground">
                        Webhook indisponível — aguarde a URL pública do túnel.
                      </p>
                    )}
                    {tunnelStatus.telegram_webhook_registered != null && (
                      <p>
                        Registrado no Telegram:{" "}
                        <Badge
                          variant={
                            tunnelStatus.telegram_webhook_registered ? "success" : "warning"
                          }
                        >
                          {tunnelStatus.telegram_webhook_registered ? "sim" : "não"}
                        </Badge>
                        {tunnelStatus.telegram_webhook_registered_url && (
                          <span className="mt-1 block font-mono text-xs text-muted-foreground">
                            {tunnelStatus.telegram_webhook_registered_url}
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="glass-card space-y-4 p-6">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Webhooks (copiar)
                </h3>
                {tunnelStatus.whatsapp_webhook_url ? (
                  <div className="space-y-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">WhatsApp (Twilio)</p>
                      <code className="mt-1 block break-all text-sm">
                        {tunnelStatus.whatsapp_webhook_url}
                      </code>
                    </div>
                    <CopyButton text={tunnelStatus.whatsapp_webhook_url} />
                    <p className="text-xs text-muted-foreground">
                      Console Twilio → Messaging → seu número → &quot;A message comes in&quot; →
                      Webhook → HTTP POST → cole esta URL.
                    </p>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Webhook WhatsApp indisponível até a URL pública ser resolvida.
                  </p>
                )}
                {tunnelStatus.telegram_mode === "webhook" && tunnelStatus.telegram_webhook_url && (
                  <div className="space-y-3 border-t border-border pt-4">
                    <div>
                      <p className="text-sm font-medium text-foreground">Telegram</p>
                      <code className="mt-1 block break-all text-sm">
                        {tunnelStatus.telegram_webhook_url}
                      </code>
                    </div>
                    <CopyButton text={tunnelStatus.telegram_webhook_url} />
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      ) : activeTab === "identity" ? (
        identityLoading ? (
          <p className="text-sm text-muted-foreground">Carregando identidade da empresa...</p>
        ) : (
          <form onSubmit={handleSaveIdentity} className="space-y-8">
            <div className="glass-card space-y-6 p-6">
              <p className="text-sm text-muted-foreground">
                Esta identidade vale para todos os agentes do seu workspace; cada agente pode
                sobrescrever campos específicos na própria configuração.
              </p>

              <div>
                <label htmlFor="company_name" className="mb-2 block text-sm font-medium text-foreground">
                  Nome da empresa
                </label>
                <input
                  id="company_name"
                  type="text"
                  className="input-field"
                  value={identityValues.company_name}
                  onChange={(e) => handleIdentityFieldChange("company_name", e.target.value)}
                />
              </div>

              <div>
                <label htmlFor="display_name" className="mb-2 block text-sm font-medium text-foreground">
                  Nome de exibição
                </label>
                <input
                  id="display_name"
                  type="text"
                  className="input-field"
                  value={identityValues.display_name}
                  onChange={(e) => handleIdentityFieldChange("display_name", e.target.value)}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Nome usado nas conversas quando diferente da razão social.
                </p>
              </div>

              <div>
                <label htmlFor="tone" className="mb-2 block text-sm font-medium text-foreground">
                  Tom de voz
                </label>
                <input
                  id="tone"
                  type="text"
                  className="input-field"
                  value={identityValues.tone}
                  onChange={(e) => handleIdentityFieldChange("tone", e.target.value)}
                  placeholder="Ex.: formal e acolhedor, descontraído, técnico"
                />
              </div>

              <div>
                <label
                  htmlFor="business_context"
                  className="mb-2 block text-sm font-medium text-foreground"
                >
                  Contexto do negócio
                </label>
                <textarea
                  id="business_context"
                  className="input-field min-h-[160px] resize-y"
                  value={identityValues.business_context}
                  maxLength={4000}
                  onChange={(e) => handleIdentityFieldChange("business_context", e.target.value)}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Descreva o que a empresa faz em alto nível. NÃO coloque preços ou políticas
                  aqui — esses vêm da Base de Conhecimento.
                </p>
              </div>

              <div>
                <label htmlFor="greeting_hint" className="mb-2 block text-sm font-medium text-foreground">
                  Dica de saudação
                  <span className="ml-1 font-normal text-muted-foreground">(opcional)</span>
                </label>
                <input
                  id="greeting_hint"
                  type="text"
                  className="input-field"
                  value={identityValues.greeting_hint}
                  onChange={(e) => handleIdentityFieldChange("greeting_hint", e.target.value)}
                  placeholder="Ex.: Cumprimente pelo nome quando souber"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button type="submit" className="btn-primary" disabled={identitySaving}>
                {identitySaving ? "Salvando..." : "Salvar identidade"}
              </button>
            </div>
          </form>
        )
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Carregando configurações...</p>
      ) : (
        <form onSubmit={handleSave} className="space-y-8">
          {activeTab === "llm" && (
            <div className="glass-card space-y-6 p-6">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">Provedor ativo:</span>
                <Badge>{activeLlm ? `${activeLlm} ativo` : "—"}</Badge>
              </div>
              {visibleCategories.map((cat) =>
                renderCategoryFields(cat, activeLlm)
              )}
            </div>
          )}

          {activeTab === "agent" && (
            <div className="glass-card space-y-6 p-6">
              <p className="text-sm text-muted-foreground">
                Temperaturas, prompt do sistema, RAG, limite de tokens e número WhatsApp do
                atendente humano — lidos do banco a cada mensagem (sem reiniciar containers).
                No escalonamento, o lead recebe o link wa.me do operador e o operador é
                notificado no WhatsApp dele.
              </p>
              {visibleCategories.map((cat) => renderCategoryFields(cat, null))}
            </div>
          )}

          {activeTab === "audio" && (
            <>
              <div className="glass-card space-y-6 p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">Provedores ativos:</span>
                  <Badge>{activeStt ? `STT: ${activeStt}` : "STT: —"}</Badge>
                  <Badge>{activeTts ? `TTS: ${activeTts}` : "TTS: —"}</Badge>
                </div>
                {visibleCategories.map((cat) =>
                  renderCategoryFields(
                    cat,
                    cat.id === "stt" ? activeStt : activeTts
                  )
                )}
              </div>

              <div className="glass-card p-6">
                <h2 className="mb-4 text-lg font-semibold text-foreground">
                  Voz personalizada (Coqui)
                </h2>
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2 md:gap-8">
                  <div className="space-y-4 rounded-xl border border-border bg-background/50 p-4">
                    <h3 className="font-medium text-foreground">Voz de referência</h3>

                    {loadingSample ? (
                      <p className="text-sm text-muted-foreground">Carregando amostra...</p>
                    ) : sampleInfo?.exists ? (
                      <div className="space-y-3">
                        <p className="text-sm font-medium text-foreground">
                          Amostra de voz atual
                        </p>
                        <ul className="space-y-1 text-sm text-muted-foreground">
                          <li>
                            <span className="text-foreground">Arquivo:</span>{" "}
                            {sampleInfo.filename}
                          </li>
                          <li>
                            <span className="text-foreground">Tamanho:</span>{" "}
                            {formatBytes(sampleInfo.size_bytes)}
                          </li>
                          <li>
                            <span className="text-foreground">Modificado:</span>{" "}
                            {formatModifiedAt(sampleInfo.modified_at)}
                          </li>
                        </ul>
                        {referencePlayUrl && (
                          <audio
                            controls
                            src={referencePlayUrl}
                            className="w-full"
                          />
                        )}
                        <p className="text-xs text-muted-foreground">
                          Caminho: <code className="text-foreground">{sampleInfo.path}</code>
                        </p>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Nenhuma amostra de voz carregada ainda.
                      </p>
                    )}

                    <div className="space-y-2 border-t border-border pt-4">
                      <label className="block text-sm font-medium text-foreground">
                        Enviar nova amostra (.wav, 1s–10MB)
                      </label>
                      <input
                        type="file"
                        accept=".wav,audio/wav,audio/*"
                        className="input-field"
                        onChange={(e) => setWavFile(e.target.files?.[0] ?? null)}
                      />
                      <button
                        type="button"
                        className="btn-primary w-full sm:w-auto"
                        disabled={uploading || !wavFile}
                        onClick={handleUploadSample}
                      >
                        {uploading ? "Enviando..." : "Enviar nova amostra"}
                      </button>
                    </div>
                  </div>

                  <div className="space-y-4 rounded-xl border border-border bg-background/50 p-4">
                    <h3 className="font-medium text-foreground">Testar voz</h3>
                    <label
                      htmlFor="testText"
                      className="block text-sm font-medium text-foreground"
                    >
                      Texto para síntese
                    </label>
                    <textarea
                      id="testText"
                      className="input-field min-h-[100px]"
                      value={testText}
                      onChange={(e) => setTestText(e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn-primary w-full sm:w-auto"
                      disabled={testingVoice}
                      onClick={handleVoiceTest}
                    >
                      {testingVoice ? "Gerando áudio..." : "Gerar e ouvir"}
                    </button>
                    {testingVoice && (
                      <p className="text-sm text-muted-foreground">
                        Gerando áudio... (pode levar ~15s)
                      </p>
                    )}
                    {testPlayUrl && (
                      <audio
                        controls
                        autoPlay
                        src={testPlayUrl}
                        className="w-full"
                      />
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="flex justify-end">
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? "Salvando..." : "Salvar alterações"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
