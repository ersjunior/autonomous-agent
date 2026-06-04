"""CSV parsing and column mapping for lead base imports."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

MAX_AUX_COLUMNS = 45

FIELD_ALIASES: dict[str, set[str]] = {
    "id_cliente": {
        "id_cliente",
        "id",
        "cliente_id",
        "id cliente",
        "codigo",
        "codigo cliente",
        "cod cliente",
    },
    "nome_cliente": {
        "nome",
        "name",
        "nome_cliente",
        "nome cliente",
        "cliente",
        "nome do cliente",
    },
    "cpf_cliente": {
        "cpf",
        "cpf_cliente",
        "cpf/cnpj",
        "cpf cnpj",
        "documento",
    },
    "email_cliente": {
        "email",
        "e-mail",
        "email_cliente",
        "e mail",
        "mail",
    },
    "telefone_1": {
        "telefone 1",
        "telefone1",
        "telefone_1",
        "phone 1",
        "phone1",
        "tel 1",
    },
    "telefone_2": {
        "telefone 2",
        "telefone2",
        "telefone_2",
        "phone 2",
        "phone2",
        "tel 2",
    },
    "telefone_3": {
        "telefone 3",
        "telefone3",
        "telefone_3",
        "phone 3",
        "phone3",
        "tel 3",
    },
}

GENERIC_PHONE_ALIASES = {
    "telefone",
    "phone",
    "tel",
    "celular",
    "fone",
    "mobile",
    "whatsapp",
}


def normalize_header(header: str) -> str:
    return header.strip().lower().replace("_", " ").replace("-", " ").strip()


def parse_csv_content(content: str) -> tuple[list[str], list[list[str]]]:
    if content.startswith("\ufeff"):
        content = content[1:]

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return [], []

    headers = [header.strip() for header in rows[0]]
    data_rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    return headers, data_rows


def build_column_mapping(headers: list[str]) -> tuple[dict[int, str], dict[str, str]]:
    """Map CSV column indexes to lead fields and build aux column labels."""
    index_to_field: dict[int, str] = {}
    assigned_fields: set[str] = set()
    generic_phone_indexes: list[int] = []
    aux_candidates: list[tuple[int, str]] = []

    for index, header in enumerate(headers):
        normalized = normalize_header(header)
        if not normalized:
            continue

        matched_field: str | None = None
        for field_name, aliases in FIELD_ALIASES.items():
            if normalized in aliases and field_name not in assigned_fields:
                matched_field = field_name
                break

        if matched_field:
            index_to_field[index] = matched_field
            assigned_fields.add(matched_field)
            continue

        if normalized in GENERIC_PHONE_ALIASES:
            generic_phone_indexes.append(index)
            continue

        aux_candidates.append((index, header.strip()))

    phone_slots = ["telefone_1", "telefone_2", "telefone_3"]
    for phone_index in generic_phone_indexes:
        for slot in phone_slots:
            if slot not in assigned_fields:
                index_to_field[phone_index] = slot
                assigned_fields.add(slot)
                break

    column_mapping: dict[str, str] = {}
    for aux_number, (index, original_header) in enumerate(aux_candidates[:MAX_AUX_COLUMNS], start=1):
        aux_key = f"aux{aux_number}"
        index_to_field[index] = aux_key
        column_mapping[aux_key] = original_header

    return index_to_field, column_mapping


def row_to_lead_data(
    row: list[str],
    index_to_field: dict[int, str],
    *,
    user_id: uuid.UUID,
    lead_base_id: uuid.UUID,
) -> dict[str, Any] | None:
    lead_data: dict[str, Any] = {
        "user_id": user_id,
        "lead_base_id": lead_base_id,
        "aux_values": {},
    }

    for index, field_name in index_to_field.items():
        value = row[index].strip() if index < len(row) else ""
        if not value:
            continue

        if field_name.startswith("aux"):
            lead_data["aux_values"][field_name] = value
        else:
            lead_data[field_name] = value

    nome = lead_data.get("nome_cliente")
    if not nome:
        id_cliente = lead_data.get("id_cliente")
        if id_cliente:
            lead_data["nome_cliente"] = id_cliente
        else:
            return None

    return lead_data
