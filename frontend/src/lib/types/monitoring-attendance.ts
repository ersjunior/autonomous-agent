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
