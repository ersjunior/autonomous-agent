export interface AvailabilityRule {
  id: string;
  user_id: string;
  agent_id: string | null;
  weekday: number;
  start_time: string;
  end_time: string;
  slot_minutes: number | null;
  timezone: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AvailabilityDayInput {
  weekday: number;
  start_time: string;
  end_time: string;
  slot_minutes?: number | null;
  timezone?: string | null;
}

export interface AvailabilityScheduleUpdate {
  days: AvailabilityDayInput[];
}

export interface AvailabilityWeekdayRow {
  weekday: number;
  label: string;
  active: boolean;
  start_time: string;
  end_time: string;
  slot_minutes: string;
}

export const WEEKDAY_ROWS: { weekday: number; label: string }[] = [
  { weekday: 0, label: "Segunda-feira" },
  { weekday: 1, label: "Terça-feira" },
  { weekday: 2, label: "Quarta-feira" },
  { weekday: 3, label: "Quinta-feira" },
  { weekday: 4, label: "Sexta-feira" },
  { weekday: 5, label: "Sábado" },
  { weekday: 6, label: "Domingo" },
];

export const DEFAULT_DAY_START = "09:00";
export const DEFAULT_DAY_END = "18:00";
export const DEFAULT_SLOT_MINUTES = "30";

export function emptyWeekdayGrid(): AvailabilityWeekdayRow[] {
  return WEEKDAY_ROWS.map(({ weekday, label }) => ({
    weekday,
    label,
    active: weekday < 5,
    start_time: DEFAULT_DAY_START,
    end_time: DEFAULT_DAY_END,
    slot_minutes: DEFAULT_SLOT_MINUTES,
  }));
}

export function gridFromRules(rules: AvailabilityRule[]): AvailabilityWeekdayRow[] {
  const byWeekday = new Map(rules.map((r) => [r.weekday, r]));
  return WEEKDAY_ROWS.map(({ weekday, label }) => {
    const rule = byWeekday.get(weekday);
    if (!rule) {
      return {
        weekday,
        label,
        active: false,
        start_time: DEFAULT_DAY_START,
        end_time: DEFAULT_DAY_END,
        slot_minutes: DEFAULT_SLOT_MINUTES,
      };
    }
    return {
      weekday,
      label,
      active: true,
      start_time: rule.start_time,
      end_time: rule.end_time,
      slot_minutes:
        rule.slot_minutes != null ? String(rule.slot_minutes) : DEFAULT_SLOT_MINUTES,
    };
  });
}

export function gridToPayload(rows: AvailabilityWeekdayRow[]): AvailabilityDayInput[] {
  return rows
    .filter((row) => row.active)
    .map((row) => ({
      weekday: row.weekday,
      start_time: row.start_time,
      end_time: row.end_time,
      slot_minutes: row.slot_minutes.trim()
        ? parseInt(row.slot_minutes, 10)
        : null,
    }));
}
