import { apiFetch, formatApiError } from "@/lib/api";
import type { Agent, AgentCreatePayload, AgentUpdatePayload } from "@/lib/types/agents";
import type { Channel } from "@/lib/types/channels";
import type {
  Campaign,
  CampaignCreatePayload,
  CampaignStartResponse,
  CampaignUpdatePayload,
} from "@/lib/types/campaigns";
import type { Lead } from "@/lib/types/leads";
import type {
  Tabulacao,
  TabulacaoCreatePayload,
  TabulacaoUpdatePayload,
} from "@/lib/types/tabulacoes";

async function parseError(res: Response, context: string): Promise<never> {
  throw new Error(await formatApiError(res, context));
}

export async function fetchAgents(): Promise<Agent[]> {
  const res = await apiFetch("/api/v1/agents/");
  if (!res.ok) {
    await parseError(res, "Erro ao listar agentes");
  }
  return res.json();
}

export async function createAgent(payload: AgentCreatePayload): Promise<Agent> {
  const res = await apiFetch("/api/v1/agents/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao criar agente");
  }
  return res.json();
}

export async function updateAgent(id: string, payload: AgentUpdatePayload): Promise<Agent> {
  const res = await apiFetch(`/api/v1/agents/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao atualizar agente");
  }
  return res.json();
}

export async function deleteAgent(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/agents/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir agente");
  }
}

export async function fetchChannels(): Promise<Channel[]> {
  const res = await apiFetch("/api/v1/channels/");
  if (!res.ok) {
    await parseError(res, "Erro ao listar canais");
  }
  return res.json();
}

export async function createChannel(body: Record<string, unknown>): Promise<Channel> {
  const res = await apiFetch("/api/v1/channels/", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao criar canal");
  }
  return res.json();
}

export async function updateChannel(
  id: string,
  body: Record<string, unknown>,
): Promise<Channel> {
  const res = await apiFetch(`/api/v1/channels/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao atualizar canal");
  }
  return res.json();
}

export async function deleteChannel(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/channels/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir canal");
  }
}

export async function fetchCampaigns(): Promise<Campaign[]> {
  const res = await apiFetch("/api/v1/campaigns/");
  if (!res.ok) {
    await parseError(res, "Erro ao listar campanhas");
  }
  return res.json();
}

export async function createCampaign(payload: CampaignCreatePayload): Promise<Campaign> {
  const res = await apiFetch("/api/v1/campaigns/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao criar campanha");
  }
  return res.json();
}

export async function updateCampaign(
  id: string,
  payload: CampaignUpdatePayload,
): Promise<Campaign> {
  const res = await apiFetch(`/api/v1/campaigns/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao atualizar campanha");
  }
  return res.json();
}

export async function deleteCampaign(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/campaigns/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir campanha");
  }
}

export async function startCampaign(id: string): Promise<CampaignStartResponse> {
  const res = await apiFetch(`/api/v1/campaigns/${id}/start`, { method: "POST" });
  if (!res.ok) {
    await parseError(res, "Erro ao iniciar campanha");
  }
  return res.json();
}

export async function updateLead(id: string, payload: Record<string, unknown>): Promise<Lead> {
  const res = await apiFetch(`/api/v1/leads/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao atualizar lead");
  }
  return res.json();
}

export async function deleteLead(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/leads/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir lead");
  }
}

export async function fetchTabulacoes(): Promise<Tabulacao[]> {
  const res = await apiFetch("/api/v1/tabulacoes/");
  if (!res.ok) {
    await parseError(res, "Erro ao listar tabulações");
  }
  return res.json();
}

export async function createTabulacao(payload: TabulacaoCreatePayload): Promise<Tabulacao> {
  const res = await apiFetch("/api/v1/tabulacoes/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao criar tabulação");
  }
  return res.json();
}

export async function updateTabulacao(
  id: string,
  payload: TabulacaoUpdatePayload,
): Promise<Tabulacao> {
  const res = await apiFetch(`/api/v1/tabulacoes/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro ao atualizar tabulação");
  }
  return res.json();
}

export async function deleteTabulacao(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/tabulacoes/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir tabulação");
  }
}

export async function deleteLeadBase(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/lead-bases/${id}`, { method: "DELETE" });
  if (!res.ok) {
    await parseError(res, "Erro ao excluir base de leads");
  }
}
