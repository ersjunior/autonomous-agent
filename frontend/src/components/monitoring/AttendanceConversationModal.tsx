"use client";

import type { AttendanceConversation } from "@/lib/types/monitoring-attendance";
import { CHANNEL_LABELS } from "@/lib/types/metrics";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";

type AttendanceConversationModalProps = {
  conversation: AttendanceConversation | null;
  loading: boolean;
  error: string;
  onClose: () => void;
};

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR");
}

function formatDurationSeconds(seconds: number | null, available: boolean): string {
  if (!available) return "Indisponível";
  if (seconds == null || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) {
    return secs > 0 ? `${mins} min ${secs}s` : `${mins} min`;
  }
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}min`;
}

function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel.toLowerCase()] ?? channel.toUpperCase();
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

export function AttendanceConversationModal({
  conversation,
  loading,
  error,
  onClose,
}: AttendanceConversationModalProps) {
  if (!conversation && !loading && !error) {
    return null;
  }

  return (
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
            <button type="button" className="btn-secondary text-sm" onClick={onClose}>
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
                  Tabulação: {conversation.tabulacao_codigo} — {conversation.tabulacao_nome}
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
          {loading && (
            <p className="text-sm text-muted-foreground">Carregando mensagens…</p>
          )}
          {error && <Alert variant="error">{error}</Alert>}
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
  );
}
