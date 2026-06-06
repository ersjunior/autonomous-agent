export type VoiceVideoParams = {
  chamadas_simultaneas: number;
  campanhas_simultaneas: number;
  tentativas_por_hora: number;
  horario_inicio: string;
  horario_fim: string;
};

export type MessagingParams = {
  chats_simultaneos: number;
  campanhas_simultaneas: number;
  tentativas_sem_resposta: number;
  minutos_segunda_mensagem: number;
  horario_inicio: string;
  horario_fim: string;
};

export type ChannelParams = VoiceVideoParams | MessagingParams;

export type ChannelSettings = {
  agent_id: string;
  channel_type: string;
  params: Record<string, string | number>;
  is_system: boolean;
  editable: boolean;
};

export type ChannelSettingsList = {
  agent_id: string;
  is_system: boolean;
  editable: boolean;
  channels: ChannelSettings[];
};

export type Activation = {
  agent_id: string;
  campaign_id: string;
  channel_type: string;
  is_running: boolean;
  started_at: string | null;
  stopped_at: string | null;
};

export type ActivationList = {
  campaign_id: string;
  agent_id: string;
  activations: Activation[];
};

export type ActivationStartResult = {
  status: "started";
  channel_type: string;
  leads_dispatched: number;
  activation: Activation;
};

export type TestDispatchPayload = {
  lead_id: string;
  agent_id: string;
  channel_type: string;
};

export type TestDispatchResult = {
  status: "sucesso" | "erro";
  channel: string;
  recipient: string | null;
  response: string | null;
  error?: string | null;
  lead_interaction_id?: string | null;
};

export type ActivationHistoryItem = {
  id: string;
  lead_id: string;
  lead_nome: string;
  campaign_id: string;
  campaign_name: string;
  channel_type: string;
  status: string;
  tentativas: number;
  data_acionamento: string | null;
  data_ultimo_contato: string | null;
  data_ultima_tentativa: string | null;
  tabulacao_codigo: string | null;
  tabulacao_nome: string | null;
  tabulacao_aplicada_em: string | null;
  is_terminal: boolean;
  is_human_mode: boolean;
};

export type ActivationHistoryList = {
  items: ActivationHistoryItem[];
  total: number;
  skip: number;
  limit: number;
};

export type ActivationHistoryFilters = {
  campaign_id?: string;
  channel_type?: string;
  status?: string;
  open_only?: boolean;
};

export type FinalizeInteractionPayload = {
  tabulacao_codigo: string;
  status_interno?: string;
};

export type FinalizeInteractionResult = {
  ok: boolean;
  lead_interaction_id: string;
  status: string;
  tabulacao_codigo: string;
  message: string | null;
};
