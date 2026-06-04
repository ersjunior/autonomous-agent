export type ChannelType = "WHATSAPP" | "TELEGRAM" | "VOICE" | "VIDEO";

export interface Channel {
  id: string;
  name?: string | null;
  type: ChannelType;
  credentials: Record<string, unknown>;
  is_active: boolean;
  is_system?: boolean;
  created_at: string;
}
