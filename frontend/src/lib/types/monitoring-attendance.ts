export type AttendanceHistoryItem = {
  lead_interaction_id: string | null;
  contact_user_id: string;
  lead_nome: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  channel: string;
  status: string | null;
  tabulacao_codigo: string | null;
  tabulacao_nome: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  duration_available: boolean;
  message_count: number;
  last_message_preview: string | null;
  has_lead: boolean;
  last_delivery_status?: string | null;
  last_delivery_error_code?: string | null;
  delivery_label?: string | null;
};

export type AttendanceHistoryList = {
  items: AttendanceHistoryItem[];
  total: number;
  skip: number;
  limit: number;
};

export type AttendanceHistoryFilters = {
  campaign_id?: string;
  channel_type?: string;
  status?: string;
  open_only?: boolean;
};

export type ConversationMessage = {
  role: "user" | "assistant";
  content: string;
  at: string;
  intent?: string | null;
};

export type AttendanceConversation = {
  lead_interaction_id: string | null;
  contact_user_id: string;
  channel: string;
  lead_nome: string | null;
  campaign_name: string | null;
  status: string | null;
  tabulacao_codigo: string | null;
  tabulacao_nome: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  duration_available: boolean;
  voice_partial_transcript: boolean;
  voice_duration_note: string | null;
  messages: ConversationMessage[];
};

export type ActiveConversationItem = {
  contact_user_id: string;
  channel: string;
  lead_nome: string | null;
  lead_interaction_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  status: string | null;
  last_message_preview: string | null;
  last_activity_at: string | null;
  message_count: number;
};

export type ActiveConversationsList = {
  items: ActiveConversationItem[];
  total: number;
  window_minutes: number;
};

/** Estado enriquecido no painel tempo real (REST + eventos WS). */
export type ActiveConversation = ActiveConversationItem & {
  last_timestamp: string;
  last_message: string;
  last_event_type?: string;
  intent?: string;
  is_escalated?: boolean;
};

export type AgentMonitoringEvent = {
  type: string;
  timestamp: string;
  channel?: string;
  user_id?: string;
  message?: string;
  response?: string;
  intent?: string;
  confidence?: number;
  agent_id?: string;
  agent_name?: string;
};
