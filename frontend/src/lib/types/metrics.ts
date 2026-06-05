export interface MetricsResponse {
  total_leads: number;
  total_acionamentos: number;
  por_status: Record<string, number>;
  por_canal: Record<string, number>;
  taxa_conversao: number;
  taxa_resposta: number;
}

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
