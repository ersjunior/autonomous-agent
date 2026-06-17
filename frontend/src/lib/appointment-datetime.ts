/** Helpers de data/hora para agendamentos (API em UTC, UI em America/Sao_Paulo). */

const TZ = "America/Sao_Paulo";

export function formatAppointmentDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Converte valor de <input type="datetime-local"> (interpretado como Brasília) para ISO UTC. */
export function brLocalInputToUtcIso(localValue: string): string {
  if (!localValue) {
    return "";
  }
  const normalized = localValue.length === 16 ? `${localValue}:00` : localValue;
  return new Date(`${normalized}-03:00`).toISOString();
}

/** Preenche datetime-local a partir de ISO UTC. */
export function utcIsoToBrLocalInput(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

export function defaultEndLocalFromStart(startLocal: string, minutes = 30): string {
  if (!startLocal) {
    return "";
  }
  const startUtc = new Date(brLocalInputToUtcIso(startLocal));
  const endUtc = new Date(startUtc.getTime() + minutes * 60_000);
  return utcIsoToBrLocalInput(endUtc.toISOString());
}

export const APPOINTMENT_STATUS_LABELS: Record<string, string> = {
  SCHEDULED: "Agendado",
  CONFIRMED: "Confirmado",
  CANCELLED: "Cancelado",
  COMPLETED: "Concluído",
  NO_SHOW: "Não compareceu",
};

export const APPOINTMENT_SOURCE_LABELS: Record<string, string> = {
  AGENT: "Agente",
  MANUAL: "Manual",
};

export function appointmentStatusVariant(
  status: string,
): "default" | "success" | "warning" | "muted" {
  switch (status) {
    case "CONFIRMED":
    case "COMPLETED":
      return "success";
    case "SCHEDULED":
      return "default";
    case "NO_SHOW":
      return "warning";
    case "CANCELLED":
      return "muted";
    default:
      return "default";
  }
}
