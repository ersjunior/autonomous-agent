export type TabulacaoCategoria = "TELEFONIA" | "NEGOCIO" | "CUSTOMIZADO";

export interface Tabulacao {
  id: string;
  user_id: string;
  nome: string;
  codigo: string;
  categoria: TabulacaoCategoria;
  is_terminal: boolean;
  is_system?: boolean;
  descricao?: string | null;
  created_at: string;
}

export interface TabulacaoCreatePayload {
  nome: string;
  codigo: string;
  categoria: TabulacaoCategoria;
  is_terminal?: boolean;
  descricao?: string | null;
}

export interface TabulacaoUpdatePayload {
  nome?: string;
  codigo?: string;
  categoria?: TabulacaoCategoria;
  is_terminal?: boolean;
  descricao?: string | null;
}
