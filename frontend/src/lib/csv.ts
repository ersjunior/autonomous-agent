import { MAX_AUX_COLUMNS } from "@/lib/types/leads";

const FIELD_ALIASES: Record<string, Set<string>> = {
  id_cliente: new Set([
    "id_cliente",
    "id",
    "cliente_id",
    "id cliente",
    "codigo",
    "codigo cliente",
    "cod cliente",
  ]),
  nome_cliente: new Set([
    "nome",
    "name",
    "nome_cliente",
    "nome cliente",
    "cliente",
    "nome do cliente",
  ]),
  cpf_cliente: new Set(["cpf", "cpf_cliente", "cpf/cnpj", "cpf cnpj", "documento"]),
  email_cliente: new Set(["email", "e-mail", "email_cliente", "e mail", "mail"]),
  telefone_1: new Set(["telefone 1", "telefone1", "telefone_1", "phone 1", "phone1", "tel 1"]),
  telefone_2: new Set(["telefone 2", "telefone2", "telefone_2", "phone 2", "phone2", "tel 2"]),
  telefone_3: new Set(["telefone 3", "telefone3", "telefone_3", "phone 3", "phone3", "tel 3"]),
};

const GENERIC_PHONE_ALIASES = new Set([
  "telefone",
  "phone",
  "tel",
  "celular",
  "fone",
  "mobile",
  "whatsapp",
]);

export interface CsvMappingResult {
  indexToField: Record<number, string>;
  columnMapping: Record<string, string>;
  headers: string[];
  rows: string[][];
}

export interface PreviewLeadRow {
  id_cliente?: string;
  nome_cliente?: string;
  cpf_cliente?: string;
  email_cliente?: string;
  telefone_1?: string;
  telefone_2?: string;
  telefone_3?: string;
  aux_values: Record<string, string>;
}

function normalizeHeader(header: string): string {
  return header.trim().toLowerCase().replace(/_/g, " ").replace(/-/g, " ").trim();
}

function parseCsvLine(line: string): string[] {
  const values: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === "," && !inQuotes) {
      values.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }

  values.push(current.trim());
  return values;
}

export function parseCsvContent(content: string): { headers: string[]; rows: string[][] } {
  const normalizedContent = content.startsWith("\ufeff") ? content.slice(1) : content;
  const lines = normalizedContent.trim().split(/\r?\n/);
  if (lines.length === 0) {
    return { headers: [], rows: [] };
  }

  const headers = parseCsvLine(lines[0]).map((header) => header.trim());
  const rows = lines
    .slice(1)
    .map(parseCsvLine)
    .filter((row) => row.some((cell) => cell.trim()));

  return { headers, rows };
}

export function buildColumnMapping(headers: string[]): CsvMappingResult {
  const indexToField: Record<number, string> = {};
  const assignedFields = new Set<string>();
  const genericPhoneIndexes: number[] = [];
  const auxCandidates: Array<{ index: number; header: string }> = [];

  headers.forEach((header, index) => {
    const normalized = normalizeHeader(header);
    if (!normalized) {
      return;
    }

    let matchedField: string | null = null;
    for (const [fieldName, aliases] of Object.entries(FIELD_ALIASES)) {
      if (aliases.has(normalized) && !assignedFields.has(fieldName)) {
        matchedField = fieldName;
        break;
      }
    }

    if (matchedField) {
      indexToField[index] = matchedField;
      assignedFields.add(matchedField);
      return;
    }

    if (GENERIC_PHONE_ALIASES.has(normalized)) {
      genericPhoneIndexes.push(index);
      return;
    }

    auxCandidates.push({ index, header: header.trim() });
  });

  const phoneSlots = ["telefone_1", "telefone_2", "telefone_3"];
  genericPhoneIndexes.forEach((phoneIndex) => {
    for (const slot of phoneSlots) {
      if (!assignedFields.has(slot)) {
        indexToField[phoneIndex] = slot;
        assignedFields.add(slot);
        break;
      }
    }
  });

  const columnMapping: Record<string, string> = {};
  auxCandidates.slice(0, MAX_AUX_COLUMNS).forEach(({ index, header }, auxIndex) => {
    const auxKey = `aux${auxIndex + 1}`;
    indexToField[index] = auxKey;
    columnMapping[auxKey] = header;
  });

  return { indexToField, columnMapping, headers, rows: [] };
}

export function mapRowToPreview(
  row: string[],
  indexToField: Record<number, string>,
): PreviewLeadRow | null {
  const preview: PreviewLeadRow = { aux_values: {} };

  Object.entries(indexToField).forEach(([index, fieldName]) => {
    const value = row[Number(index)]?.trim() ?? "";
    if (!value) {
      return;
    }

    if (fieldName.startsWith("aux")) {
      preview.aux_values[fieldName] = value;
      return;
    }

    preview[fieldName as keyof Omit<PreviewLeadRow, "aux_values">] = value;
  });

  if (!preview.nome_cliente) {
    if (preview.id_cliente) {
      preview.nome_cliente = preview.id_cliente;
    } else {
      return null;
    }
  }

  return preview;
}

export function buildPreviewRows(
  rows: string[][],
  indexToField: Record<number, string>,
): PreviewLeadRow[] {
  return rows
    .map((row) => mapRowToPreview(row, indexToField))
    .filter((row): row is PreviewLeadRow => row !== null);
}

export function analyzeCsv(content: string): CsvMappingResult {
  const { headers, rows } = parseCsvContent(content);
  const mapping = buildColumnMapping(headers);
  return { ...mapping, headers, rows };
}
