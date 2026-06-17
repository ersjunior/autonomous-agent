import { apiFetch, formatApiError } from "@/lib/api";
import type {
  AvailabilityRule,
  AvailabilityScheduleUpdate,
} from "@/lib/types/availability";

async function parseError(res: Response, context: string): Promise<never> {
  throw new Error(await formatApiError(res, context));
}

function tenantUrl(): string {
  return "/api/v1/availability-rules";
}

function agentUrl(agentId: string): string {
  return `/api/v1/agents/${agentId}/availability-rules`;
}

export async function getAvailabilityRules(
  agentId?: string | null,
): Promise<AvailabilityRule[]> {
  const url = agentId ? agentUrl(agentId) : tenantUrl();
  const res = await apiFetch(url);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar disponibilidade");
  }
  return res.json();
}

export async function putAvailabilitySchedule(
  payload: AvailabilityScheduleUpdate,
  agentId?: string | null,
): Promise<AvailabilityRule[]> {
  const url = agentId ? agentUrl(agentId) : tenantUrl();
  const res = await apiFetch(url, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao salvar disponibilidade");
  }
  return res.json();
}
