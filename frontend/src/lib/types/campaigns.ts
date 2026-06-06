export interface Campaign {
  id: string;
  name: string;
  agent_id: string;
  channel_types: string[];
  status: string;
  leads_count: number;
  is_system?: boolean;
  created_at: string;
}

export interface CampaignCreatePayload {
  name: string;
  agent_id: string;
  channel_types: string[];
}

export interface CampaignUpdatePayload {
  name?: string;
  agent_id?: string;
  channel_types?: string[];
  status?: string;
}

export interface CampaignStartResponse {
  status: string;
  leads_dispatched: number;
}

export interface CampaignStopResponse {
  status: string;
  activations_stopped: number;
}
