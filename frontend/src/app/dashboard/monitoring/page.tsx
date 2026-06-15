"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  API_URL,
  assumeHandoff,
  finalizeHandoff,
  formatApiError,
  getActiveHandoffs,
  getTabulacaoCatalog,
  reactivateHandoff,
  type HandoffContact,
  type TabulacaoCatalogItem,
} from "@/lib/api";
import { fetchAttendanceHistory, fetchAttendanceMessages, getActiveConversations } from "@/lib/api-monitoring";
import { fetchCampaigns } from "@/lib/api-entities";
import type {
  ActiveConversation,
  ActiveConversationItem,
  AgentMonitoringEvent,
  AttendanceConversation,
  AttendanceHistoryItem,
  ConversationMessage,
} from "@/lib/types/monitoring-attendance";
import type { Campaign } from "@/lib/types/campaigns";
import { deliveryBadgeVariant } from "@/lib/delivery-label";
import { AttendanceConversationModal } from "@/components/monitoring/AttendanceConversationModal";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

const WS_BACKOFF_MS = [1000, 2000, 5000, 10000, 30000] as const;
const ACTIVE_TTL_CHECK_MS = 30_000;
const DEFAULT_ACTIVE_WINDOW_MINUTES = 10;
const PREVIEW_MAX_LEN = 120;
const ALL_PERIOD_WINDOW_MINUTES = 0;

const ACTIVE_WINDOW_OPTIONS = [
  { label: "10 min", windowMinutes: 10 },
  { label: "Última Hora", windowMinutes: 60 },
  { label: "Dia", windowMinutes: 1440 },
  { label: "Mês", windowMinutes: 43200 },
  { label: "Ano", windowMinutes: 525600 },
  { label: "Todo o período", windowMinutes: ALL_PERIOD_WINDOW_MINUTES },
] as const;

const FINALIZE_CATEGORIES = new Set(["NEGOCIO", "CUSTOMIZADO"]);
const HISTORY_CHANNELS = ["whatsapp", "telegram", "voice"] as const;
const HISTORY_LIMIT = 50;
const HISTORY_STATUS_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "pendente", label: "Pendente" },
  { value: "acionado", label: "Acionado" },
  { value: "em_andamento", label: "Em andamento" },
  { value: "convertido", label: "Convertido" },
  { value: "recusou", label: "Recusou" },
  { value: "nao_atendido", label: "Não atendido" },
  { value: "erro", label: "Erro" },
] as const;

type TabId = "live" | "history";

function formatDurationSince(iso: string | null): string {
  if (!iso) return "—";
  const start = new Date(iso).getTime();
  const mins = Math.floor((Date.now() - start) / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}min`;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR");
}

function formatDurationSeconds(seconds: number | null, available: boolean): string {
  if (!available) {
    return "Indisponível";
  }
  if (seconds == null || seconds < 0) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) {
    return secs > 0 ? `${mins} min ${secs}s` : `${mins} min`;
  }
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}min`;
}

function channelLabel(channel: string): string {
  return channel.toUpperCase();
}

function statusBadgeVariant(
  status: string | null,
): "default" | "warning" | "success" | "muted" {
  if (!status) return "muted";
  const s = status.toLowerCase();
  if (s === "convertido") return "success";
  if (s === "em_andamento" || s === "acionado") return "default";
  if (s === "recusou" || s === "nao_atendido" || s === "erro") return "warning";
  return "muted";
}

function contactLabel(item: AttendanceHistoryItem): string {
  return item.lead_nome || item.contact_user_id;
}

function conversationKey(channel: string, userId: string): string {
  return `${channel.toLowerCase()}:${userId}`;
}

function truncatePreview(text: string, max = PREVIEW_MAX_LEN): string {
  const cleaned = text.trim();
  if (!cleaned) return "";
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1)}…`;
}

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 60) return "agora";
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `há ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `há ${hours}h`;
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function activeConversationLabel(conv: ActiveConversation): string {
  return conv.lead_nome || conv.contact_user_id;
}

function restItemToConversation(item: ActiveConversationItem): ActiveConversation {
  const lastMessage = item.last_message_preview ?? "";
  return {
    ...item,
    last_timestamp: item.last_activity_at ?? new Date().toISOString(),
    last_message: lastMessage,
    last_message_preview: lastMessage,
    is_escalated: false,
  };
}

function applyAgentEvent(
  prev: Record<string, ActiveConversation>,
  event: AgentMonitoringEvent,
): Record<string, ActiveConversation> {
  const channel = (event.channel ?? "").toLowerCase();
  const userId = event.user_id;
  if (!channel || !userId) return prev;

  const key = conversationKey(channel, userId);
  const existing = prev[key];
  const next: ActiveConversation = existing
    ? { ...existing }
    : {
        contact_user_id: userId,
        channel,
        lead_nome: null,
        lead_interaction_id: null,
        agent_id: event.agent_id ?? null,
        agent_name: event.agent_name ?? null,
        status: null,
        last_message_preview: "",
        last_activity_at: event.timestamp,
        message_count: 0,
        last_timestamp: event.timestamp,
        last_message: "",
        is_escalated: false,
      };

  next.last_timestamp = event.timestamp;
  next.last_activity_at = event.timestamp;
  next.last_event_type = event.type;
  if (event.agent_id) next.agent_id = event.agent_id;
  if (event.agent_name) next.agent_name = event.agent_name;

  switch (event.type) {
    case "message_received":
      if (event.message) next.last_message = event.message;
      break;
    case "intent_detected":
      if (event.intent) next.intent = event.intent;
      break;
    case "response_sent":
      if (event.response) next.last_message = event.response;
      next.is_escalated = false;
      break;
    case "escalated":
      if (event.response) next.last_message = event.response;
      next.is_escalated = true;
      break;
    default:
      break;
  }

  next.last_message_preview = truncatePreview(
    next.last_message || next.last_message_preview || "",
  );

  return { ...prev, [key]: next };
}

function pruneStaleConversations(
  prev: Record<string, ActiveConversation>,
  windowMinutes: number,
): Record<string, ActiveConversation> {
  if (windowMinutes === ALL_PERIOD_WINDOW_MINUTES) {
    return prev;
  }
  const cutoff = Date.now() - windowMinutes * 60 * 1000;
  let changed = false;
  const next: Record<string, ActiveConversation> = { ...prev };
  for (const [key, conv] of Object.entries(next)) {
    const ts = new Date(conv.last_timestamp).getTime();
    if (Number.isNaN(ts) || ts < cutoff) {
      delete next[key];
      changed = true;
    }
  }
  return changed ? next : prev;
}

type ConversationFetchTarget = {
  lead_interaction_id: string | null;
  channel: string;
  contact_user_id: string;
};

function appendLiveEventToConversation(
  conv: AttendanceConversation,
  event: AgentMonitoringEvent,
): AttendanceConversation | null {
  if (
    conversationKey(conv.channel, conv.contact_user_id) !==
    conversationKey(event.channel ?? "", event.user_id ?? "")
  ) {
    return null;
  }

  let newMsg: ConversationMessage | null = null;
  if (event.type === "message_received" && event.message) {
    newMsg = {
      role: "user",
      content: event.message,
      at: event.timestamp,
      intent: event.intent,
    };
  } else if (
    (event.type === "response_sent" || event.type === "escalated") &&
    event.response
  ) {
    newMsg = {
      role: "assistant",
      content: event.response,
      at: event.timestamp,
    };
  }
  if (!newMsg) return null;

  const last = conv.messages[conv.messages.length - 1];
  if (
    last &&
    last.role === newMsg.role &&
    last.content === newMsg.content &&
    last.at === newMsg.at
  ) {
    return null;
  }

  return { ...conv, messages: [...conv.messages, newMsg] };
}

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<TabId>("live");

  return (
    <>
      <PageHeader
        title="Monitoramento"
        description={
          activeTab === "live"
            ? "Conversas ativas em tempo real e modo humano."
            : "Histórico de atendimentos com conversas para supervisão."
        }
      />

      <div className="mb-6 flex flex-wrap gap-2 border-b border-border">
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "live"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("live")}
        >
          Tempo real
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium ${
            activeTab === "history"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground"
          }`}
          onClick={() => setActiveTab("history")}
        >
          Histórico de atendimentos
        </button>
      </div>

      {activeTab === "live" ? <LiveMonitoringPanel /> : <AttendanceHistoryPanel />}
    </>
  );
}

function LiveMonitoringPanel() {
  const [conversations, setConversations] = useState<Record<string, ActiveConversation>>({});
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [selectedWindowMinutes, setSelectedWindowMinutes] = useState(DEFAULT_ACTIVE_WINDOW_MINUTES);
  const [activeWindowMinutes, setActiveWindowMinutes] = useState(DEFAULT_ACTIVE_WINDOW_MINUTES);
  const [conversation, setConversation] = useState<AttendanceConversation | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationError, setConversationError] = useState("");
  const [connected, setConnected] = useState(false);
  const [handoffs, setHandoffs] = useState<HandoffContact[]>([]);
  const [handoffLoading, setHandoffLoading] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [finalizeTarget, setFinalizeTarget] = useState<HandoffContact | null>(null);
  const [tabulacoes, setTabulacoes] = useState<TabulacaoCatalogItem[]>([]);
  const [selectedTabulacao, setSelectedTabulacao] = useState("");
  const [finalizeLoading, setFinalizeLoading] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const hasConnectedBeforeRef = useRef(false);
  const openConversationKeyRef = useRef<string | null>(null);

  const loadActiveConversations = useCallback(async (windowMinutes?: number) => {
    const resolvedWindow = windowMinutes ?? selectedWindowMinutes;
    setConversationsError(null);
    setConversationsLoading(true);
    try {
      const data = await getActiveConversations(resolvedWindow);
      setActiveWindowMinutes(data.window_minutes);
      const mapped: Record<string, ActiveConversation> = {};
      for (const item of data.items) {
        const key = conversationKey(item.channel, item.contact_user_id);
        mapped[key] = restItemToConversation(item);
      }
      setConversations(mapped);
    } catch (err) {
      setConversationsError(
        err instanceof Error ? err.message : "Erro ao carregar conversas ativas",
      );
    } finally {
      setConversationsLoading(false);
    }
  }, [selectedWindowMinutes]);

  const loadHandoffs = useCallback(async () => {
    setHandoffLoading(true);
    setHandoffError(null);
    try {
      const res = await getActiveHandoffs();
      if (!res.ok) {
        throw new Error(await formatApiError(res, "Falha ao carregar modo humano"));
      }
      const data = (await res.json()) as HandoffContact[];
      setHandoffs(data);
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      setHandoffLoading(false);
    }
  }, []);

  const loadTabulacoes = useCallback(async () => {
    try {
      const res = await getTabulacaoCatalog();
      if (!res.ok) return;
      const data = (await res.json()) as TabulacaoCatalogItem[];
      setTabulacoes(
        data.filter((t) => FINALIZE_CATEGORIES.has(t.categoria.toUpperCase())),
      );
    } catch {
      // modal mostrará erro ao abrir se vazio
    }
  }, []);

  useEffect(() => {
    void loadHandoffs();
    void loadTabulacoes();
    void loadActiveConversations(selectedWindowMinutes);
    const interval = setInterval(() => void loadHandoffs(), 30000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount inicial; troca de janela via handleWindowChange
  }, [loadHandoffs, loadTabulacoes]);

  useEffect(() => {
    const interval = setInterval(() => {
      setConversations((prev) => pruneStaleConversations(prev, activeWindowMinutes));
    }, ACTIVE_TTL_CHECK_MS);
    return () => clearInterval(interval);
  }, [activeWindowMinutes]);

  useEffect(() => {
    const wsUrl = `${API_URL.replace(/^http/, "ws")}/api/v1/monitoring/ws`;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    let intentionalClose = false;

    function scheduleReconnect() {
      const delay =
        WS_BACKOFF_MS[Math.min(reconnectAttempt, WS_BACKOFF_MS.length - 1)] ??
        WS_BACKOFF_MS[WS_BACKOFF_MS.length - 1];
      reconnectAttempt += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    }

    function connect() {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectAttempt = 0;
        if (hasConnectedBeforeRef.current) {
          void loadActiveConversations(selectedWindowMinutes);
        } else {
          hasConnectedBeforeRef.current = true;
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!intentionalClose) {
          scheduleReconnect();
        }
      };

      ws.onerror = () => {
        setConnected(false);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AgentMonitoringEvent;
          setConversations((prev) => applyAgentEvent(prev, data));
          setConversation((conv) => {
            if (!conv || !openConversationKeyRef.current) return conv;
            const updated = appendLiveEventToConversation(conv, data);
            return updated ?? conv;
          });
          if (data.type === "escalated") {
            void loadHandoffs();
          }
        } catch {
          // ignore malformed events
        }
      };
    }

    connect();

    return () => {
      intentionalClose = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      wsRef.current = null;
    };
  }, [loadHandoffs, loadActiveConversations, selectedWindowMinutes]);

  async function handleAssume(channel: string, userId: string) {
    const key = `${channel}:${userId}`;
    setActionKey(key);
    try {
      const res = await assumeHandoff(channel, userId);
      if (!res.ok) {
        throw new Error(await formatApiError(res, "Falha ao assumir"));
      }
      await loadHandoffs();
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : "Erro ao assumir");
    } finally {
      setActionKey(null);
    }
  }

  async function handleReactivate(channel: string, userId: string) {
    const key = `${channel}:${userId}`;
    setActionKey(key);
    try {
      const res = await reactivateHandoff(channel, userId);
      if (!res.ok) {
        throw new Error(await formatApiError(res, "Falha ao devolver ao bot"));
      }
      await loadHandoffs();
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : "Erro ao devolver ao bot");
    } finally {
      setActionKey(null);
    }
  }

  function openFinalizeModal(item: HandoffContact) {
    setFinalizeTarget(item);
    setSelectedTabulacao("");
    setHandoffError(null);
    if (tabulacoes.length === 0) {
      void loadTabulacoes();
    }
  }

  function closeFinalizeModal() {
    setFinalizeTarget(null);
    setSelectedTabulacao("");
    setFinalizeLoading(false);
  }

  async function handleFinalizeConfirm() {
    if (!finalizeTarget || !selectedTabulacao) {
      setHandoffError("Selecione uma tabulação para finalizar.");
      return;
    }
    setFinalizeLoading(true);
    setHandoffError(null);
    try {
      const res = await finalizeHandoff(
        finalizeTarget.channel,
        finalizeTarget.user_id,
        selectedTabulacao,
      );
      if (!res.ok) {
        throw new Error(await formatApiError(res, "Falha ao finalizar"));
      }
      closeFinalizeModal();
      await loadHandoffs();
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : "Erro ao finalizar");
    } finally {
      setFinalizeLoading(false);
    }
  }

  const waitingCount = handoffs.filter((h) => !h.is_assumed).length;
  const assumedCount = handoffs.filter((h) => h.is_assumed).length;

  const sortedConversations = Object.values(conversations).sort(
    (a, b) => new Date(b.last_timestamp).getTime() - new Date(a.last_timestamp).getTime(),
  );

  async function openConversation(item: ConversationFetchTarget) {
    openConversationKeyRef.current = conversationKey(item.channel, item.contact_user_id);
    setConversationLoading(true);
    setConversationError("");
    setConversation(null);
    try {
      const data = await fetchAttendanceMessages(item);
      setConversation(data);
    } catch (err) {
      setConversationError(err instanceof Error ? err.message : "Erro ao abrir conversa.");
      openConversationKeyRef.current = null;
    } finally {
      setConversationLoading(false);
    }
  }

  function closeConversation() {
    openConversationKeyRef.current = null;
    setConversation(null);
    setConversationError("");
  }

  function handleWindowChange(windowMinutes: number) {
    setSelectedWindowMinutes(windowMinutes);
    void loadActiveConversations(windowMinutes);
  }

  return (
    <>
      <div className="mb-4 flex justify-end">
        <Badge variant={connected ? "success" : "muted"}>
          <span className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                connected ? "animate-pulse bg-success" : "bg-muted-foreground"
              }`}
            />
            {connected ? "Conectado" : "Desconectado"}
          </span>
        </Badge>
      </div>

      <section className="glass-card mb-6 p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-foreground">Modo humano</h2>
          <Badge variant="warning">{waitingCount} aguardando</Badge>
          {assumedCount > 0 && (
            <Badge variant="success">{assumedCount} assumido(s)</Badge>
          )}
          <button
            type="button"
            className="btn-secondary text-sm"
            onClick={() => void loadHandoffs()}
            disabled={handoffLoading}
          >
            Atualizar
          </button>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          Contatos escalados — assuma, finalize com tabulação ou devolva ao bot. Timeouts
          automáticos: fila curta sem assumir devolve ao bot; após assumir, finalização
          longa gera abandono (NEG:ABANDONO).
        </p>
        {handoffError && (
          <p className="mb-3 text-sm text-destructive">{handoffError}</p>
        )}
        {handoffLoading && handoffs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Carregando...</p>
        ) : handoffs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nenhum contato em modo humano no momento.
          </p>
        ) : (
          <div className="space-y-2">
            {handoffs.map((item) => {
              const key = `${item.channel}:${item.user_id}`;
              const busy = actionKey === key;
              const label = item.lead_name || item.user_id;
              const sinceIso = item.is_assumed
                ? item.human_assumed_at
                : item.escalated_at;
              return (
                <div
                  key={key}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 bg-background/40 px-4 py-3"
                >
                  <Badge variant={item.is_assumed ? "success" : "warning"}>
                    {item.is_assumed ? "Assumido" : "Aguardando"}
                  </Badge>
                  <Badge variant="muted">{item.channel}</Badge>
                  <span className="text-sm font-medium text-foreground">{label}</span>
                  {item.lead_name && (
                    <span className="text-xs text-muted-foreground">{item.user_id}</span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {item.is_assumed ? "assumido há" : "há"}{" "}
                    {formatDurationSince(sinceIso)}
                  </span>
                  {item.ttl_seconds != null && (
                    <span className="text-xs text-muted-foreground">
                      TTL Redis {Math.ceil(item.ttl_seconds / 60)} min
                    </span>
                  )}
                  <div className="ml-auto flex flex-wrap gap-2">
                    {!item.is_assumed ? (
                      <button
                        type="button"
                        className="btn-primary text-sm"
                        disabled={busy}
                        onClick={() => void handleAssume(item.channel, item.user_id)}
                      >
                        {busy ? "..." : "Assumir"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn-primary text-sm"
                        disabled={busy}
                        onClick={() => openFinalizeModal(item)}
                      >
                        Finalizar
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-secondary text-sm"
                      disabled={busy}
                      onClick={() => void handleReactivate(item.channel, item.user_id)}
                    >
                      {busy ? "..." : "Devolver ao bot"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {finalizeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="glass-card w-full max-w-md space-y-4 p-6">
            <h3 className="text-lg font-semibold text-foreground">Finalizar atendimento</h3>
            <p className="text-sm text-muted-foreground">
              {finalizeTarget.lead_name || finalizeTarget.user_id} — escolha a tabulação de
              encerramento.
            </p>
            <label className="block text-sm font-medium text-foreground">Tabulação</label>
            <select
              className="input-field w-full"
              value={selectedTabulacao}
              onChange={(e) => setSelectedTabulacao(e.target.value)}
            >
              <option value="">Selecione...</option>
              {tabulacoes.map((t) => (
                <option key={t.id} value={t.codigo}>
                  {t.codigo} — {t.nome}
                </option>
              ))}
            </select>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={closeFinalizeModal}
                disabled={finalizeLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void handleFinalizeConfirm()}
                disabled={finalizeLoading || !selectedTabulacao}
              >
                {finalizeLoading ? "Finalizando..." : "Confirmar"}
              </button>
            </div>
          </div>
        </div>
      )}

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-foreground">Atendimentos em andamento</h2>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Janela
          </span>
          <div className="inline-flex flex-wrap gap-1 rounded-xl border border-border/60 bg-card/50 p-1 backdrop-blur-sm">
            {ACTIVE_WINDOW_OPTIONS.map((option) => {
              const active = selectedWindowMinutes === option.windowMinutes;
              return (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => handleWindowChange(option.windowMinutes)}
                  disabled={conversationsLoading}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    active
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {conversationsLoading && (
            <span className="text-xs text-muted-foreground">Atualizando…</span>
          )}
        </div>

        {conversationsError && (
          <p className="text-sm text-destructive">{conversationsError}</p>
        )}

        {conversationsLoading && sortedConversations.length === 0 ? (
          <div className="glass-card p-8 text-center text-muted-foreground">
            Carregando conversas ativas…
          </div>
        ) : sortedConversations.length === 0 ? (
          <div className="glass-card p-8 text-center text-muted-foreground">
            Nenhum atendimento em andamento no momento.
          </div>
        ) : (
          <div className="space-y-3">
            {sortedConversations.map((conv) => {
              const key = conversationKey(conv.channel, conv.contact_user_id);
              return (
                <button
                  key={key}
                  type="button"
                  className="glass-card w-full cursor-pointer p-5 text-left transition hover:border-primary/40 hover:bg-muted/10"
                  onClick={() =>
                    void openConversation({
                      lead_interaction_id: conv.lead_interaction_id,
                      channel: conv.channel,
                      contact_user_id: conv.contact_user_id,
                    })
                  }
                >
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold text-foreground">
                      {activeConversationLabel(conv)}
                    </span>
                    <Badge variant="muted">
                      {channelLabel(conv.channel)}
                    </Badge>
                    {conv.status && (
                      <Badge variant={statusBadgeVariant(conv.status)}>{conv.status}</Badge>
                    )}
                    {conv.is_escalated && <Badge variant="warning">Escalado</Badge>}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {formatRelativeTime(conv.last_timestamp)}
                    </span>
                  </div>

                  {conv.agent_name && (
                    <p className="mb-2 text-sm text-muted-foreground">
                      Atendido por:{" "}
                      <span className="font-medium text-foreground">{conv.agent_name}</span>
                    </p>
                  )}

                  {conv.intent && (
                    <p className="mb-2 text-xs text-muted-foreground">
                      Intenção: {conv.intent}
                    </p>
                  )}

                  <p className="line-clamp-2 text-sm text-foreground">
                    {conv.last_message_preview || conv.last_message || "—"}
                  </p>

                  {conv.message_count > 0 && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {conv.message_count} mensagem(ns) no histórico
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </section>

      <AttendanceConversationModal
        conversation={conversation}
        loading={conversationLoading}
        error={conversationError}
        onClose={closeConversation}
      />
    </>
  );
}

function AttendanceHistoryPanel() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [items, setItems] = useState<AttendanceHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterCampaignId, setFilterCampaignId] = useState("");
  const [filterChannel, setFilterChannel] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [conversation, setConversation] = useState<AttendanceConversation | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationError, setConversationError] = useState("");

  const currentPage = Math.floor(skip / HISTORY_LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_LIMIT));
  const canPrev = skip > 0;
  const canNext = skip + HISTORY_LIMIT < total;

  useEffect(() => {
    fetchCampaigns()
      .then(setCampaigns)
      .catch(() => {
        // filtros opcionais
      });
  }, []);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchAttendanceHistory(skip, HISTORY_LIMIT, {
        campaign_id: filterCampaignId || undefined,
        channel_type: filterChannel || undefined,
        status: filterStatus || undefined,
        open_only: openOnly,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar histórico.");
    } finally {
      setLoading(false);
    }
  }, [skip, filterCampaignId, filterChannel, filterStatus, openOnly]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  function handleFilterChange(updater: () => void) {
    updater();
    setSkip(0);
  }

  async function openConversation(item: AttendanceHistoryItem) {
    setConversationLoading(true);
    setConversationError("");
    setConversation(null);
    try {
      const data = await fetchAttendanceMessages(item);
      setConversation(data);
    } catch (err) {
      setConversationError(err instanceof Error ? err.message : "Erro ao abrir conversa.");
    } finally {
      setConversationLoading(false);
    }
  }

  function closeConversation() {
    setConversation(null);
    setConversationError("");
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="error">{error}</Alert>}

      <div className="glass-card grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-sm font-medium text-foreground">
          Campanha
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterCampaignId}
            onChange={(e) =>
              handleFilterChange(() => setFilterCampaignId(e.target.value))
            }
          >
            <option value="">Todas</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Canal
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterChannel}
            onChange={(e) => handleFilterChange(() => setFilterChannel(e.target.value))}
          >
            <option value="">Todos</option>
            {HISTORY_CHANNELS.map((ch) => (
              <option key={ch} value={ch}>
                {channelLabel(ch)}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-foreground">
          Status
          <select
            className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={filterStatus}
            onChange={(e) => handleFilterChange(() => setFilterStatus(e.target.value))}
          >
            {HISTORY_STATUS_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-end gap-2 pb-2 text-sm font-medium text-foreground">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={openOnly}
            onChange={(e) => handleFilterChange(() => setOpenOnly(e.target.checked))}
          />
          Só abertos
        </label>
      </div>

      <div className="glass-card overflow-x-auto">
        <table className="w-full min-w-[1100px] text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-muted-foreground">
              <th className="px-4 py-3 font-medium">Contato / Lead</th>
              <th className="px-4 py-3 font-medium">Campanha</th>
              <th className="px-4 py-3 font-medium">Canal</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Tabulação</th>
              <th className="px-4 py-3 font-medium">Início</th>
              <th className="px-4 py-3 font-medium">Duração</th>
              <th className="px-4 py-3 font-medium">Msgs</th>
              <th className="px-4 py-3 font-medium">Preview</th>
              <th className="px-4 py-3 font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                  Carregando…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                  Nenhum atendimento encontrado.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr
                  key={
                    item.lead_interaction_id ??
                    `${item.channel}:${item.contact_user_id}`
                  }
                  className="border-b border-border/60 hover:bg-muted/20"
                >
                  <td className="px-4 py-3">
                    <span className="font-medium text-foreground">
                      {contactLabel(item)}
                    </span>
                    {!item.has_lead && (
                      <span className="ml-2 inline-flex">
                        <Badge variant="muted">Órfão</Badge>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {item.campaign_name ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="muted">{channelLabel(item.channel)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex flex-wrap items-center gap-2">
                      {item.status ? (
                        <Badge variant={statusBadgeVariant(item.status)}>
                          {item.status}
                        </Badge>
                      ) : (
                        "—"
                      )}
                      {item.channel === "whatsapp" && item.delivery_label && (
                        <Badge variant={deliveryBadgeVariant(item.delivery_label)}>
                          {item.delivery_label}
                        </Badge>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {item.tabulacao_codigo
                      ? `${item.tabulacao_codigo} — ${item.tabulacao_nome ?? ""}`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDateTime(item.started_at)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDurationSeconds(
                      item.duration_seconds,
                      item.duration_available,
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{item.message_count}</td>
                  <td className="max-w-[200px] truncate px-4 py-3 text-muted-foreground">
                    {item.last_message_preview ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20"
                      onClick={() => void openConversation(item)}
                    >
                      Abrir conversa
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Exibindo {total === 0 ? 0 : skip + 1}–{Math.min(skip + HISTORY_LIMIT, total)} de{" "}
          {total} atendimentos
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={!canPrev || loading}
            onClick={() => setSkip(Math.max(0, skip - HISTORY_LIMIT))}
          >
            Anterior
          </button>
          <span className="text-sm text-muted-foreground">
            Página {currentPage} de {totalPages}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={!canNext || loading}
            onClick={() => setSkip(skip + HISTORY_LIMIT)}
          >
            Próxima
          </button>
        </div>
      </div>

      <AttendanceConversationModal
        conversation={conversation}
        loading={conversationLoading}
        error={conversationError}
        onClose={closeConversation}
      />
    </div>
  );
}
