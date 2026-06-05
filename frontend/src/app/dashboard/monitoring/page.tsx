"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  API_URL,
  formatApiError,
  getActiveHandoffs,
  reactivateHandoff,
  type HandoffContact,
} from "@/lib/api";
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

function formatDurationSince(iso: string | null): string {
  if (!iso) return "—";
  const start = new Date(iso).getTime();
  const mins = Math.floor((Date.now() - start) / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}min`;
}

export default function MonitoringPage() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [handoffs, setHandoffs] = useState<HandoffContact[]>([]);
  const [handoffLoading, setHandoffLoading] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const [reactivatingKey, setReactivatingKey] = useState<string | null>(null);
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

  useEffect(() => {
    void loadHandoffs();
    const interval = setInterval(() => void loadHandoffs(), 30000);
    return () => clearInterval(interval);
  }, [loadHandoffs]);

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

  async function handleReactivate(channel: string, userId: string) {
    const key = `${channel}:${userId}`;
    setReactivatingKey(key);
    try {
      const res = await reactivateHandoff(channel, userId);
      if (!res.ok) {
        throw new Error(await formatApiError(res, "Falha ao reativar"));
      }
      await loadHandoffs();
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : "Erro ao reativar");
    } finally {
      setReactivatingKey(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Monitoramento"
        description="Feed em tempo real de eventos do agente."
        actions={
          <Badge variant={connected ? "success" : "muted"}>
            <span className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  connected ? "bg-success animate-pulse" : "bg-muted-foreground"
                }`}
              />
              {connected ? "Conectado" : "Desconectado"}
            </span>
          </Badge>
        }
      />

      <section className="glass-card mb-6 p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-foreground">Modo humano</h2>
          <Badge variant="warning">{handoffs.length} aguardando</Badge>
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
          Contatos escalados — o bot não responde até reativação manual ou expiração do TTL.
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
              return (
                <div
                  key={key}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 bg-background/40 px-4 py-3"
                >
                  <Badge variant="muted">{item.channel}</Badge>
                  <span className="text-sm text-foreground">{item.user_id}</span>
                  <span className="text-xs text-muted-foreground">
                    há {formatDurationSince(item.escalated_at)}
                  </span>
                  {item.ttl_seconds != null && (
                    <span className="text-xs text-muted-foreground">
                      TTL {Math.ceil(item.ttl_seconds / 60)} min
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn-primary ml-auto text-sm"
                    disabled={reactivatingKey === key}
                    onClick={() => void handleReactivate(item.channel, item.user_id)}
                  >
                    {reactivatingKey === key ? "Reativando..." : "Devolver ao bot"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>

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
