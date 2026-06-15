import { apiFetch, formatApiError } from "@/lib/api";
import type {
  ActiveConversationsList,
  AttendanceConversation,
  AttendanceHistoryFilters,
  AttendanceHistoryList,
} from "@/lib/types/monitoring-attendance";

async function parseError(res: Response, context: string): Promise<never> {
  throw new Error(await formatApiError(res, context));
}

export async function fetchAttendanceHistory(
  skip: number,
  limit: number,
  filters: AttendanceHistoryFilters = {},
): Promise<AttendanceHistoryList> {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  });
  if (filters.campaign_id) {
    params.set("campaign_id", filters.campaign_id);
  }
  if (filters.channel_type) {
    params.set("channel_type", filters.channel_type);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.open_only) {
    params.set("open_only", "true");
  }
  const res = await apiFetch(`/api/v1/monitoring/attendance-history?${params.toString()}`);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar histórico de atendimentos");
  }
  return res.json();
}

export async function getActiveConversations(
  windowMinutes?: number,
): Promise<ActiveConversationsList> {
  const params = new URLSearchParams();
  if (windowMinutes !== undefined) {
    params.set("window_minutes", String(windowMinutes));
  }
  const query = params.toString();
  const res = await apiFetch(
    `/api/v1/monitoring/active-conversations${query ? `?${query}` : ""}`,
  );
  if (!res.ok) {
    await parseError(res, "Erro ao carregar conversas ativas");
  }
  return res.json();
}

export async function fetchAttendanceMessages(
  item: { lead_interaction_id: string | null; channel: string; contact_user_id: string },
): Promise<AttendanceConversation> {
  if (item.lead_interaction_id) {
    const res = await apiFetch(
      `/api/v1/monitoring/attendance/${encodeURIComponent(item.lead_interaction_id)}/messages`,
    );
    if (!res.ok) {
      await parseError(res, "Erro ao carregar conversa");
    }
    return res.json();
  }
  const params = new URLSearchParams({
    channel: item.channel,
    contact_user_id: item.contact_user_id,
  });
  const res = await apiFetch(`/api/v1/monitoring/contact-messages?${params.toString()}`);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar conversa");
  }
  return res.json();
}
