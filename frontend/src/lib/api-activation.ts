import { apiFetch, formatApiError } from "@/lib/api";
import type {
  Activation,
  ActivationHistoryFilters,
  ActivationHistoryList,
  ActivationList,
  ActivationStartResult,
  ChannelSettings,
  ChannelSettingsList,
  FinalizeInteractionPayload,
  FinalizeInteractionResult,
  TestDispatchPayload,
  TestDispatchResult,
} from "@/lib/types/activation";

async function parseError(res: Response, context: string): Promise<never> {
  throw new Error(await formatApiError(res, context));
}

export async function getChannelSettings(agentId: string): Promise<ChannelSettingsList> {
  const res = await apiFetch(`/api/v1/agents/${agentId}/channel-settings`);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar parâmetros do agente");
  }
  return res.json();
}

export async function getChannelSettingsForChannel(
  agentId: string,
  channelType: string,
): Promise<ChannelSettings> {
  const res = await apiFetch(
    `/api/v1/agents/${agentId}/channel-settings/${encodeURIComponent(channelType)}`,
  );
  if (!res.ok) {
    await parseError(res, "Erro ao carregar parâmetros do canal");
  }
  return res.json();
}

export async function updateChannelSettings(
  agentId: string,
  channelType: string,
  params: Record<string, string | number>,
): Promise<ChannelSettings> {
  const res = await apiFetch(
    `/api/v1/agents/${agentId}/channel-settings/${encodeURIComponent(channelType)}`,
    {
      method: "PUT",
      body: JSON.stringify({ params }),
    },
  );
  if (!res.ok) {
    await parseError(res, "Erro ao salvar parâmetros");
  }
  return res.json();
}

export async function getActivations(campaignId: string): Promise<ActivationList> {
  const res = await apiFetch(`/api/v1/campaigns/${campaignId}/activations`);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar acionamentos");
  }
  return res.json();
}

export async function startActivation(
  campaignId: string,
  channelType: string,
): Promise<ActivationStartResult> {
  const res = await apiFetch(
    `/api/v1/campaigns/${campaignId}/activations/${encodeURIComponent(channelType)}/start`,
    { method: "POST" },
  );
  if (!res.ok) {
    await parseError(res, "Erro ao iniciar acionamento");
  }
  return res.json();
}

export async function stopActivation(
  campaignId: string,
  channelType: string,
): Promise<Activation> {
  const res = await apiFetch(
    `/api/v1/campaigns/${campaignId}/activations/${encodeURIComponent(channelType)}/stop`,
    { method: "POST" },
  );
  if (!res.ok) {
    await parseError(res, "Erro ao parar acionamento");
  }
  return res.json();
}

export async function testDispatch(payload: TestDispatchPayload): Promise<TestDispatchResult> {
  const res = await apiFetch("/api/v1/activation/test-dispatch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    await parseError(res, "Erro no disparo de teste");
  }
  return res.json();
}

export async function fetchActivationHistory(
  skip: number,
  limit: number,
  filters: ActivationHistoryFilters = {},
): Promise<ActivationHistoryList> {
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
  const res = await apiFetch(`/api/v1/activation/history?${params.toString()}`);
  if (!res.ok) {
    await parseError(res, "Erro ao carregar histórico de acionamentos");
  }
  return res.json();
}

export async function finalizeInteraction(
  interactionId: string,
  payload: FinalizeInteractionPayload,
): Promise<FinalizeInteractionResult> {
  const res = await apiFetch(
    `/api/v1/activation/interactions/${encodeURIComponent(interactionId)}/finalize`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    await parseError(res, "Erro ao finalizar atendimento");
  }
  return res.json();
}
