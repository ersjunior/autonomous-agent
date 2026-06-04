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
