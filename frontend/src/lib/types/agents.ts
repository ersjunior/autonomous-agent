export type AgentMode = "ACTIVE" | "RECEPTIVE";

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  mode: AgentMode;
  status: string;
  config: Record<string, unknown>;
  is_system?: boolean;
  created_at: string;
}

export interface AgentCreatePayload {
  name: string;
  description?: string | null;
  mode: AgentMode;
  config?: Record<string, unknown>;
}

export interface AgentUpdatePayload {
  name?: string;
  description?: string | null;
  mode?: AgentMode;
  status?: string;
  config?: Record<string, unknown>;
}
