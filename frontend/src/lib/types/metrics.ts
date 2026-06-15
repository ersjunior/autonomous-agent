export interface MetricsResponse {
  total_leads: number;
  total_acionamentos: number;
  por_status: Record<string, number>;
  por_canal: Record<string, number>;
  taxa_conversao: number;
  taxa_resposta: number;
}

export interface AgentMetricsRow {
  agent_id: string;
  agent_name: string;
  mode: string;
  total_leads: number;
  total_acionamentos: number;
  por_status: Record<string, number>;
  por_canal: Record<string, number>;
  taxa_conversao: number;
  taxa_resposta: number;
}

export interface AgentMetricsResponse {
  agents: AgentMetricsRow[];
}

export const AGENT_MODE_LABELS: Record<string, string> = {
  ACTIVE: "Ativo",
  RECEPTIVE: "Receptivo",
};

export interface DashboardCards {
  agents: number;
  active_channels: number;
  leads: number;
  active_campaigns: number;
}

export interface DashboardSummaryResponse {
  cards: DashboardCards;
  leads_acionados: number;
  leads_virgens: number;
  tentativas_por_canal: Record<string, number>;
  tentativas_por_status: Record<string, number>;
}

/** Filtro de canal — seletor na home do dashboard. */
export type DashboardChannelFilter = "whatsapp" | "telegram" | "voice" | null;

export interface DashboardCampaignRow {
  campaign_id: string;
  campaign_name: string;
  leads: number;
  data_recebimento: string | null;
  data_inicio: string | null;
  data_fim: string | null;
  tentativas: number;
  spin: number;
  contato: number;
  cpc: number;
  sucesso: number;
  conversao: number;
}

export interface DashboardCampaignsResponse {
  campaigns: DashboardCampaignRow[];
}

export const STATUS_ORDER = [
  "pendente",
  "acionado",
  "em_andamento",
  "nao_atendido",
  "convertido",
  "recusou",
  "erro",
] as const;

export const STATUS_LABELS: Record<string, string> = {
  pendente: "Pendente",
  acionado: "Acionado",
  em_andamento: "Em andamento",
  nao_atendido: "Não atendido",
  convertido: "Convertido",
  recusou: "Recusou",
  erro: "Erro",
};

export const STATUS_COLORS: Record<string, string> = {
  convertido: "#22c55e",
  recusou: "#ef4444",
  em_andamento: "#3b82f6",
  nao_atendido: "#6b7280",
  acionado: "#eab308",
  erro: "#f97316",
  pendente: "#d1d5db",
};

export const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  voice: "Voz",
};

export const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#25D366",
  telegram: "#0088cc",
  voice: "#8b5cf6",
};

export interface ChannelQueueMetrics {
  total_enfileirados: number;
  total_atendidos: number;
  total_abandonados: number;
  tempo_medio_espera: number;
  taxa_abandono: number;
  nivel_servico: number;
  tamanho_fila_atual: number;
}

export interface QueueMetricsResponse {
  period_days: number;
  service_level_target_seconds: number;
  total_enfileirados: number;
  total_atendidos: number;
  total_abandonados: number;
  tempo_medio_espera: number;
  taxa_abandono: number;
  nivel_servico: number;
  tamanho_fila_atual: number;
  por_canal: Record<string, ChannelQueueMetrics>;
  abandono_apenas_voz: boolean;
  abandono_disponivel_inbound: boolean;
}
