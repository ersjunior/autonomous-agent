import { apiFetch, formatApiError } from "@/lib/api";
import type { TunnelStatusResponse } from "@/lib/types/tunnel";

export async function fetchTunnelStatus(): Promise<TunnelStatusResponse> {
  const res = await apiFetch("/api/v1/tunnel/status");
  if (!res.ok) {
    throw new Error(await formatApiError(res, "Erro ao carregar status do túnel"));
  }
  return res.json() as Promise<TunnelStatusResponse>;
}
