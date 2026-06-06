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
import { fetchAttendanceHistory, fetchAttendanceMessages } from "@/lib/api-monitoring";
import { fetchCampaigns } from "@/lib/api-entities";
import type {
  AttendanceConversation,
  AttendanceHistoryItem,
} from "@/lib/types/monitoring-attendance";
import type { Campaign } from "@/lib/types/campaigns";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

interface AgentEvent {
  type: string;
  timestamp: string;
  channel?: string;
  user_id?: string;
  message?: string;
  response?: string;
  intent?: string;
  confidence?: number;
}

const EVENT_LABELS: Record<string, string> = {
  message_received: "Mensagem recebida",
  intent_detected: "Intenção detectada",
  response_sent: "Resposta enviada",
  escalated: "Escalada",
};

const EVENT_VARIANTS: Record<string, "default" | "warning" | "success" | "muted"> = {
  message_received: "default",
  intent_detected: "warning",
  response_sent: "success",
  escalated: "muted",
};

const FINALIZE_CATEGORIES = new Set(["NEGOCIO", "CUSTOMIZADO"]);
const HISTORY_CHANNELS = ["whatsapp", "telegram", "voice", "video"] as const;
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

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<TabId>("live");

  return (
    <>
      <PageHeader
        title="Monitoramento"
        description={
          activeTab === "live"
            ? "Feed em tempo real de eventos do agente e modo humano."
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
  const [events, setEvents] = useState<AgentEvent[]>([]);
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
    const interval = setInterval(() => void loadHandoffs(), 30000);
    return () => clearInterval(interval);
  }, [loadHandoffs, loadTabulacoes]);

  useEffect(() => {
    const wsUrl = `${API_URL.replace(/^http/, "ws")}/api/v1/monitoring/ws`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as AgentEvent;
        setEvents((prev) => [data, ...prev].slice(0, 100));
        if (data.type === "escalated") {
          void loadHandoffs();
        }
      } catch {
        // ignore malformed events
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [loadHandoffs]);

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

      {events.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Aguardando eventos... Envie uma mensagem pelo WhatsApp ou Telegram.
        </div>
      ) : (
        <div className="space-y-3">
          {events.map((event, index) => (
            <div key={`${event.timestamp}-${index}`} className="glass-card p-5">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Badge variant={EVENT_VARIANTS[event.type] ?? "muted"}>
                  {EVENT_LABELS[event.type] ?? event.type}
                </Badge>
                {event.channel && (
                  <span className="text-xs uppercase text-muted-foreground">
                    {event.channel}
                  </span>
                )}
                <span className="ml-auto text-xs text-muted-foreground">
                  {new Date(event.timestamp).toLocaleString("pt-BR")}
                </span>
              </div>

              {event.user_id && (
                <p className="text-xs text-muted-foreground">Usuário: {event.user_id}</p>
              )}
              {event.message && (
                <p className="mt-2 text-sm text-foreground">
                  <span className="font-medium text-muted-foreground">Mensagem:</span>{" "}
                  {event.message}
                </p>
              )}
              {event.intent && (
                <p className="mt-2 text-sm text-foreground">
                  <span className="font-medium text-muted-foreground">Intenção:</span>{" "}
                  {event.intent}
                  {event.confidence !== undefined &&
                    ` (${(event.confidence * 100).toFixed(0)}%)`}
                </p>
              )}
              {event.response && (
                <p className="mt-2 text-sm text-foreground">
                  <span className="font-medium text-muted-foreground">Resposta:</span>{" "}
                  {event.response}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
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
                    {item.status ? (
                      <Badge variant={statusBadgeVariant(item.status)}>
                        {item.status}
                      </Badge>
                    ) : (
                      "—"
                    )}
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

      {(conversation || conversationLoading || conversationError) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="glass-card flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden">
            <div className="border-b border-border p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Conversa</h3>
                  {conversation && (
                    <p className="mt-1 text-sm text-muted-foreground">
                      {conversation.lead_nome || conversation.contact_user_id}
                      {conversation.campaign_name && ` · ${conversation.campaign_name}`}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  onClick={closeConversation}
                >
                  Fechar
                </button>
              </div>
              {conversation && (
                <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge variant="muted">{channelLabel(conversation.channel)}</Badge>
                  {conversation.status && (
                    <Badge variant={statusBadgeVariant(conversation.status)}>
                      {conversation.status}
                    </Badge>
                  )}
                  {conversation.tabulacao_codigo && (
                    <span>
                      Tabulação: {conversation.tabulacao_codigo} —{" "}
                      {conversation.tabulacao_nome}
                    </span>
                  )}
                  <span>Início: {formatDateTime(conversation.started_at)}</span>
                  <span>Fim: {formatDateTime(conversation.ended_at)}</span>
                  <span>
                    Duração:{" "}
                    {formatDurationSeconds(
                      conversation.duration_seconds,
                      conversation.duration_available,
                    )}
                  </span>
                </div>
              )}
              {conversation?.voice_partial_transcript && conversation.voice_duration_note && (
                <div className="mt-4">
                  <Alert variant="warning">{conversation.voice_duration_note}</Alert>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-6">
              {conversationLoading && (
                <p className="text-sm text-muted-foreground">Carregando mensagens…</p>
              )}
              {conversationError && (
                <Alert variant="error">{conversationError}</Alert>
              )}
              {conversation && conversation.messages.length === 0 && (
                <p className="text-sm text-muted-foreground">Nenhuma mensagem registrada.</p>
              )}
              {conversation && conversation.messages.length > 0 && (
                <div className="space-y-3">
                  {conversation.messages.map((msg, idx) => (
                    <div
                      key={`${msg.at}-${idx}`}
                      className={`flex ${msg.role === "user" ? "justify-start" : "justify-end"}`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                          msg.role === "user"
                            ? "bg-muted text-foreground"
                            : "bg-primary/15 text-foreground"
                        }`}
                      >
                        <p className="mb-1 text-xs font-medium text-muted-foreground">
                          {msg.role === "user" ? "Cliente" : "Agente"}
                          {msg.intent ? ` · ${msg.intent}` : ""}
                        </p>
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {formatDateTime(msg.at)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
