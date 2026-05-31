"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
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

export default function MonitoringPage() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

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
      } catch {
        // ignore malformed events
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

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
