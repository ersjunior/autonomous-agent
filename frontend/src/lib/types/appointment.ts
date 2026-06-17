export type AppointmentStatus =
  | "SCHEDULED"
  | "CONFIRMED"
  | "CANCELLED"
  | "COMPLETED"
  | "NO_SHOW";

export type AppointmentSource = "AGENT" | "MANUAL";

export interface Appointment {
  id: string;
  user_id: string;
  lead_id: string;
  lead_name?: string | null;
  agent_id?: string | null;
  starts_at: string;
  ends_at: string;
  title: string;
  notes?: string | null;
  status: AppointmentStatus;
  created_by: AppointmentSource;
  channel?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppointmentCreatePayload {
  lead_id: string;
  starts_at: string;
  ends_at: string;
  title: string;
  notes?: string | null;
}

export interface AppointmentUpdatePayload {
  status?: AppointmentStatus;
  notes?: string | null;
  starts_at?: string;
  ends_at?: string;
}

export interface AppointmentListFilters {
  status?: AppointmentStatus;
  lead_id?: string;
  from?: string;
  to?: string;
}
