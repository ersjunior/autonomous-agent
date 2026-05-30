"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";

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
  intent_detected: "Intencao detectada",
  response_sent: "Resposta enviada",
  escalated: "Escalada",
};

const EVENT_COLORS: Record<string, string> = {
  message_received: "bg-blue-100 text-blue-800",
  intent_detected: "bg-yellow-100 text-yellow-800",
  response_sent: "bg-green-100 text-green-800",
  escalated: "bg-red-100 text-red-800",
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
    <main className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Monitoramento</h1>
          <p className="mt-1 text-gray-600">
            Feed em tempo real de eventos do agente.
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${
            connected
              ? "bg-green-100 text-green-800"
              : "bg-gray-100 text-gray-600"
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              connected ? "bg-green-500" : "bg-gray-400"
            }`}
          />
          {connected ? "Conectado" : "Desconectado"}
        </span>
      </div>

      {events.length === 0 ? (
        <p className="text-gray-500">
          Aguardando eventos... Envie uma mensagem pelo WhatsApp ou Telegram.
        </p>
      ) : (
        <div className="space-y-3">
          {events.map((event, index) => (
            <div
              key={`${event.timestamp}-${index}`}
              className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span
                  className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                    EVENT_COLORS[event.type] ?? "bg-gray-100 text-gray-800"
                  }`}
                >
                  {EVENT_LABELS[event.type] ?? event.type}
                </span>
                {event.channel && (
                  <span className="text-xs uppercase text-gray-500">
                    {event.channel}
                  </span>
                )}
                <span className="ml-auto text-xs text-gray-400">
                  {new Date(event.timestamp).toLocaleString("pt-BR")}
                </span>
              </div>

              {event.user_id && (
                <p className="text-xs text-gray-500">Usuario: {event.user_id}</p>
              )}
              {event.message && (
                <p className="mt-1 text-sm text-gray-700">
                  <span className="font-medium">Mensagem:</span> {event.message}
                </p>
              )}
              {event.intent && (
                <p className="mt-1 text-sm text-gray-700">
                  <span className="font-medium">Intencao:</span> {event.intent}
                  {event.confidence !== undefined &&
                    ` (${(event.confidence * 100).toFixed(0)}%)`}
                </p>
              )}
              {event.response && (
                <p className="mt-1 text-sm text-gray-700">
                  <span className="font-medium">Resposta:</span> {event.response}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
