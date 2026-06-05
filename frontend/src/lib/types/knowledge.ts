export type KBSourceType = "UPLOAD" | "MANUAL";
export type KBDocumentStatus = "PROCESSING" | "READY" | "ERROR";

export interface KBDocument {
  id: string;
  user_id: string;
  title: string;
  source_type: KBSourceType;
  filename: string | null;
  mime_type: string | null;
  status: KBDocumentStatus;
  error_message: string | null;
  is_system: boolean;
  chunk_count: number;
  total_chunks_estimated: number;
  chunks_processed: number;
  created_at: string;
}

export interface KBManualCreatePayload {
  title: string;
  content: string;
}
