export interface Lead {
  id: string;
  lead_base_id: string;
  id_cliente?: string | null;
  nome_cliente: string;
  cpf_cliente?: string | null;
  email_cliente?: string | null;
  telefone_1?: string | null;
  telefone_2?: string | null;
  telefone_3?: string | null;
  aux_values: Record<string, string>;
  created_at: string;
}

export interface LeadListResponse {
  items: Lead[];
  total: number;
  skip: number;
  limit: number;
}

export interface LeadBase {
  id: string;
  campaign_id: string;
  data_recebimento: string;
  data_inicio?: string | null;
  data_fim?: string | null;
  column_mapping: Record<string, string>;
  channel_types: string[];
  leads_count: number;
  created_at: string;
}

export interface DevolutivaFile {
  data: string;
  filename: string;
  size_bytes: number;
}

export interface LeadBaseListResponse {
  items: LeadBase[];
  total: number;
  skip: number;
  limit: number;
}

export interface Campaign {
  id: string;
  name: string;
  agent_id: string;
  channel_types: string[];
  status: string;
  leads_count: number;
  created_at: string;
}

export const FIXED_LEAD_COLUMNS = [
  { key: "id_cliente", label: "ID Cliente" },
  { key: "nome_cliente", label: "Nome" },
  { key: "cpf_cliente", label: "CPF" },
  { key: "email_cliente", label: "Email" },
  { key: "telefone_1", label: "Telefone 1" },
  { key: "telefone_2", label: "Telefone 2" },
  { key: "telefone_3", label: "Telefone 3" },
] as const;

export type FixedLeadColumnKey = (typeof FIXED_LEAD_COLUMNS)[number]["key"];

export const MAX_AUX_COLUMNS = 45;

export function sortAuxKeys(keys: string[]): string[] {
  return [...keys].sort((a, b) => {
    const numA = Number.parseInt(a.replace("aux", ""), 10);
    const numB = Number.parseInt(b.replace("aux", ""), 10);
    return numA - numB;
  });
}

export function nextAuxKey(existing: Record<string, string>): string | null {
  for (let index = 1; index <= MAX_AUX_COLUMNS; index += 1) {
    const key = `aux${index}`;
    if (!(key in existing)) {
      return key;
    }
  }
  return null;
}
