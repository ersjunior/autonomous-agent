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
  fetchAvatarImage,
  fetchVideoBlob,
  fetchVoiceSampleAudio,
  formatApiError,
  getAvatarImageInfo,
  getSettings,
  getVoiceSampleInfo,
  testAvatar,
  testVoice,
  updateSettings,
  uploadAvatarImage,
  uploadVoiceSample,
} from "@/lib/api";
import { fetchTunnelStatus } from "@/lib/api-tunnel";
import type {
  AvatarImageInfo,
  AvatarImageUploadResponse,
  AvatarTestResponse,
  SettingCategory,
  SettingField,
  SettingsResponse,
  VoiceSampleInfo,
  VoiceSampleUploadResponse,
  VoiceTestResponse,
} from "@/lib/types/settings";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { CopyButton } from "@/components/ui/CopyButton";
import { PageHeader } from "@/components/ui/PageHeader";
import type { TunnelStatusLevel, TunnelStatusResponse } from "@/lib/types/tunnel";

const SECRET_MASK = "********";
const DEFAULT_TEST_TEXT =
  "Olá! Esta é uma demonstração da minha voz personalizada, falando em português.";
const DEFAULT_AVATAR_TEST_TEXT =
  "Olá! Esta é uma demonstração do avatar em vídeo, falando com a minha voz personalizada em português.";

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
const AVATAR_CATEGORIES = new Set(["avatar"]);

type TabId = "llm" | "agent" | "audio" | "video" | "tunnel";

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
  if (p === "sadtalker" && key.startsWith("sadtalker_")) {
    return true;
  }
  if (p === "did" && key.startsWith("did_")) {
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
  const [settingsVersion, setSettingsVersion] = useState(0);
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

  const [imageFile, setImageFile] = useState<File | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [avatarInfo, setAvatarInfo] = useState<AvatarImageInfo | null>(null);
  const [loadingAvatarInfo, setLoadingAvatarInfo] = useState(false);
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState<string | null>(null);
  const avatarPreviewObjectUrl = useRef<string | null>(null);

  const [avatarTestText, setAvatarTestText] = useState(DEFAULT_AVATAR_TEST_TEXT);
  const [testingAvatar, setTestingAvatar] = useState(false);
  const [testVideoUrl, setTestVideoUrl] = useState<string | null>(null);
  const testVideoObjectUrl = useRef<string | null>(null);

  const [tunnelStatus, setTunnelStatus] = useState<TunnelStatusResponse | null>(null);
  const [tunnelLoading, setTunnelLoading] = useState(false);
  const [tunnelError, setTunnelError] = useState("");

  const loadTunnelStatus = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setTunnelLoading(true);
    setTunnelError("");
    try {
      setTunnelStatus(await fetchTunnelStatus());
    } catch (err) {
      setTunnelError(err instanceof Error ? err.message : "Erro ao carregar status do túnel.");
      setTunnelStatus(null);
    } finally {
      setTunnelLoading(false);
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
      setSettingsVersion(data.settings_version ?? 0);

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

  const loadAvatarPreview = useCallback(async () => {
    revokeBlobUrl(avatarPreviewObjectUrl);
    setAvatarPreviewUrl(null);
    try {
      const blob = await fetchAvatarImage();
      const url = URL.createObjectURL(blob);
      avatarPreviewObjectUrl.current = url;
      setAvatarPreviewUrl(url);
    } catch {
      setError("Erro ao carregar preview da imagem do avatar.");
    }
  }, []);

  const loadAvatarImageInfo = useCallback(async () => {
    setLoadingAvatarInfo(true);
    try {
      const res = await getAvatarImageInfo();
      if (!res.ok) {
        setAvatarInfo(null);
        return;
      }
      const info: AvatarImageInfo = await res.json();
      setAvatarInfo(info);
      if (info.exists) {
        await loadAvatarPreview();
      } else {
        revokeBlobUrl(avatarPreviewObjectUrl);
        setAvatarPreviewUrl(null);
      }
    } catch {
      setAvatarInfo(null);
    } finally {
      setLoadingAvatarInfo(false);
    }
  }, [loadAvatarPreview]);

  useEffect(() => {
    loadSettings();
    return () => {
      revokeBlobUrl(referenceObjectUrl);
      revokeBlobUrl(testObjectUrl);
      revokeBlobUrl(avatarPreviewObjectUrl);
      revokeBlobUrl(testVideoObjectUrl);
    };
  }, [loadSettings]);

  useEffect(() => {
    if (activeTab === "audio" && !loading) {
      loadVoiceSampleInfo();
    }
  }, [activeTab, loading, loadVoiceSampleInfo]);

  useEffect(() => {
    if (activeTab === "video" && !loading) {
      loadAvatarImageInfo();
    }
  }, [activeTab, loading, loadAvatarImageInfo]);

  useEffect(() => {
    if (activeTab === "tunnel") {
      void loadTunnelStatus();
    }
  }, [activeTab, loadTunnelStatus]);

  const visibleCategories = useMemo(() => {
    const allowed =
      activeTab === "llm"
        ? LLM_CATEGORIES
        : activeTab === "agent"
          ? AGENT_CATEGORIES
          : activeTab === "video"
            ? AVATAR_CATEGORIES
            : AUDIO_CATEGORIES;
    return categories.filter((c) => allowed.has(c.id));
  }, [categories, activeTab]);

  const activeLlm = formatValue(runtime.llm_provider);
  const activeStt = formatValue(runtime.stt_provider);
  const activeTts = formatValue(runtime.tts_provider);
  const activeAvatar = formatValue(runtime.avatar_provider);

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
      setSettingsVersion(data.settings_version ?? 0);

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

  async function handleUploadAvatarImage() {
    if (!imageFile) {
      setError("Selecione uma imagem (.png, .jpg ou .jpeg).");
      return;
    }

    setUploadingImage(true);
    setError("");
    try {
      const res = await uploadAvatarImage(imageFile);
      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro ao enviar imagem do avatar"));
        }
        return;
      }

      const data: AvatarImageUploadResponse = await res.json();
      const dims =
        data.width && data.height ? ` — ${data.width}×${data.height}px` : "";
      setSuccess(
        `${data.message} (${formatBytes(data.size_bytes)}${dims}) — ${data.filename}`
      );
      setImageFile(null);
      await loadSettings();
      await loadAvatarImageInfo();
    } catch {
      setError("Erro de conexão no upload da imagem.");
    } finally {
      setUploadingImage(false);
    }
  }

  async function handleAvatarTest() {
    setTestingAvatar(true);
    setError("");
    revokeBlobUrl(testVideoObjectUrl);
    setTestVideoUrl(null);

    try {
      const res = await testAvatar(avatarTestText);

      if (!res.ok) {
        if (res.status !== 401) {
          setError(await formatApiError(res, "Erro no teste de avatar"));
        }
        return;
      }

      const data: AvatarTestResponse = await res.json();
      const blob = await fetchVideoBlob(data.video_url);
      const url = URL.createObjectURL(blob);
      testVideoObjectUrl.current = url;
      setTestVideoUrl(url);
      setSuccess("Vídeo de teste gerado com sucesso.");
    } catch (err) {
      if (err instanceof Error && err.message.includes("carregar vídeo")) {
        setError(err.message);
      } else {
        setError("Erro de conexão no teste de avatar.");
      }
    } finally {
      setTestingAvatar(false);
    }
  }

  function renderCategoryFields(cat: SettingCategory, providerKey: string | null) {
    const fields = cat.fields.filter((f) => f.key !== "avatar_default_image");
    return (
      <div key={cat.id} className="space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {cat.label}
        </h3>
        {fields.map((field) => {
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
            versão {settingsVersion}
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
            activeTab === "video"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("video")}
        >
          Avatar / Vídeo
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
            </p>
            <button
              type="button"
              className="btn-secondary"
              disabled={tunnelLoading}
              onClick={() => void loadTunnelStatus()}
            >
              {tunnelLoading ? "Atualizando..." : "Atualizar"}
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

          {activeTab === "video" && (
            <>
              <div className="glass-card space-y-6 p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground">Provedor ativo:</span>
                  <Badge>
                    {activeAvatar ? `${activeAvatar} ativo` : "—"}
                  </Badge>
                  {activeAvatar === "sadtalker" && (
                    <span className="text-xs text-muted-foreground">
                      Requer imagem de rosto + Coqui (aba Áudio)
                    </span>
                  )}
                  {activeAvatar === "did" && (
                    <span className="text-xs text-muted-foreground">
                      Usa URL de imagem e TTS interno da D-ID
                    </span>
                  )}
                </div>
                {visibleCategories.map((cat) =>
                  renderCategoryFields(cat, activeAvatar)
                )}
              </div>

              <div className="glass-card p-6">
                <h2 className="mb-4 text-lg font-semibold text-foreground">
                  Avatar em vídeo (SadTalker / D-ID)
                </h2>
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2 md:gap-8">
                  <div className="space-y-4 rounded-xl border border-border bg-background/50 p-4">
                    <h3 className="font-medium text-foreground">Imagem do avatar</h3>

                    {loadingAvatarInfo ? (
                      <p className="text-sm text-muted-foreground">
                        Carregando imagem...
                      </p>
                    ) : avatarInfo?.exists ? (
                      <div className="space-y-3">
                        <p className="text-sm font-medium text-foreground">
                          Imagem atual
                        </p>
                        <ul className="space-y-1 text-sm text-muted-foreground">
                          <li>
                            <span className="text-foreground">Arquivo:</span>{" "}
                            {avatarInfo.filename}
                          </li>
                          <li>
                            <span className="text-foreground">Tamanho:</span>{" "}
                            {formatBytes(avatarInfo.size_bytes)}
                          </li>
                          {avatarInfo.width && avatarInfo.height && (
                            <li>
                              <span className="text-foreground">Dimensões:</span>{" "}
                              {avatarInfo.width}×{avatarInfo.height}px
                            </li>
                          )}
                          <li>
                            <span className="text-foreground">Modificado:</span>{" "}
                            {formatModifiedAt(avatarInfo.modified_at)}
                          </li>
                        </ul>
                        {avatarPreviewUrl && (
                          <img
                            src={avatarPreviewUrl}
                            alt="Preview do avatar"
                            className="max-h-48 w-full rounded-lg border border-border object-contain"
                          />
                        )}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Nenhuma imagem de avatar carregada.
                      </p>
                    )}

                    <div className="space-y-2 border-t border-border pt-4">
                      <label className="block text-sm font-medium text-foreground">
                        Enviar imagem do avatar (.png, .jpg — mín. 256×256, até 10MB)
                      </label>
                      <p className="text-xs text-muted-foreground">
                        Use uma foto nítida, rosto de frente, boa iluminação.
                      </p>
                      <input
                        type="file"
                        accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                        className="input-field"
                        onChange={(e) => setImageFile(e.target.files?.[0] ?? null)}
                      />
                      <button
                        type="button"
                        className="btn-primary w-full sm:w-auto"
                        disabled={uploadingImage || !imageFile}
                        onClick={handleUploadAvatarImage}
                      >
                        {uploadingImage
                          ? "Enviando..."
                          : "Enviar imagem do avatar"}
                      </button>
                    </div>
                  </div>

                  <div className="space-y-4 rounded-xl border border-border bg-background/50 p-4">
                    <h3 className="font-medium text-foreground">Testar avatar</h3>
                    <label
                      htmlFor="avatarTestText"
                      className="block text-sm font-medium text-foreground"
                    >
                      Texto para o vídeo
                    </label>
                    <textarea
                      id="avatarTestText"
                      className="input-field min-h-[100px]"
                      value={avatarTestText}
                      onChange={(e) => setAvatarTestText(e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn-primary w-full sm:w-auto"
                      disabled={testingAvatar}
                      onClick={handleAvatarTest}
                    >
                      {testingAvatar ? "Gerando vídeo..." : "Gerar e ver vídeo"}
                    </button>
                    {testingAvatar && (
                      <p className="text-sm text-muted-foreground">
                        Gerando vídeo... (pode levar ~25s)
                      </p>
                    )}
                    {testVideoUrl && (
                      <video
                        controls
                        autoPlay
                        src={testVideoUrl}
                        className="w-full rounded-lg border border-border"
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
