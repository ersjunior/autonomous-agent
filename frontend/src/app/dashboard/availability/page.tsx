"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  getAvailabilityRules,
  putAvailabilitySchedule,
} from "@/lib/api-availability";
import { fetchAgents } from "@/lib/api-entities";
import type { Agent } from "@/lib/types/agents";
import type { AvailabilityWeekdayRow } from "@/lib/types/availability";
import {
  emptyWeekdayGrid,
  gridFromRules,
  gridToPayload,
} from "@/lib/types/availability";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";

type ScopeMode = "workspace" | "agent";

function compareTime(a: string, b: string): number {
  const [ah, am] = a.split(":").map(Number);
  const [bh, bm] = b.split(":").map(Number);
  return ah * 60 + am - (bh * 60 + bm);
}

export default function AvailabilityPage() {
  const [scopeMode, setScopeMode] = useState<ScopeMode>("workspace");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState("");
  const [rows, setRows] = useState<AvailabilityWeekdayRow[]>(emptyWeekdayGrid);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const editableAgents = useMemo(
    () => agents.filter((a) => !a.is_system),
    [agents],
  );

  const selectedAgent = useMemo(
    () => editableAgents.find((a) => a.id === agentId) ?? null,
    [editableAgents, agentId],
  );

  const loadGrid = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const targetAgentId = scopeMode === "agent" ? agentId || null : null;
      if (scopeMode === "agent" && !targetAgentId) {
        setRows(emptyWeekdayGrid());
        return;
      }
      const rules = await getAvailabilityRules(targetAgentId);
      setRows(gridFromRules(rules));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar grade.");
    } finally {
      setLoading(false);
    }
  }, [scopeMode, agentId]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }
    fetchAgents()
      .then((data) => {
        setAgents(data);
        const custom = data.filter((a) => !a.is_system);
        if (custom.length > 0) {
          setAgentId(custom[0].id);
        }
      })
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    loadGrid();
  }, [loadGrid]);

  function updateRow(
    weekday: number,
    patch: Partial<AvailabilityWeekdayRow>,
  ) {
    setRows((prev) =>
      prev.map((row) => (row.weekday === weekday ? { ...row, ...patch } : row)),
    );
  }

  function validateGrid(): string | null {
    for (const row of rows) {
      if (!row.active) {
        continue;
      }
      if (compareTime(row.start_time, row.end_time) >= 0) {
        return `${row.label}: o horário de início deve ser anterior ao fim.`;
      }
      if (row.slot_minutes.trim()) {
        const minutes = parseInt(row.slot_minutes, 10);
        if (Number.isNaN(minutes) || minutes <= 0) {
          return `${row.label}: duração do slot inválida.`;
        }
      }
    }
    return null;
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    const validationError = validateGrid();
    if (validationError) {
      setError(validationError);
      return;
    }
    if (scopeMode === "agent" && !agentId) {
      setError("Selecione um agente.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const targetAgentId = scopeMode === "agent" ? agentId : null;
      const saved = await putAvailabilitySchedule(
        { days: gridToPayload(rows) },
        targetAgentId,
      );
      setRows(gridFromRules(saved));
      setSuccess("Grade de disponibilidade salva com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar grade.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Disponibilidade"
        description="Configure os horários em que o agendamento pode oferecer slots."
      />

      {error && <Alert variant="error">{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      <div className="glass-card mb-6 space-y-3 p-4 text-sm text-muted-foreground">
        <p>
          Dias desmarcados ficam <strong className="text-foreground">sem horários disponíveis</strong>{" "}
          naquele dia — o que você salva aqui substitui por completo a grade deste escopo.
        </p>
        <p>
          Regras por agente <strong className="text-foreground">substituem</strong> as do workspace
          quando o agente atende. Sem regras cadastradas, vale o padrão do sistema (seg–sex,
          09:00–18:00, slots de 30 min).
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        <div className="glass-card space-y-4 p-6">
          <h2 className="text-lg font-semibold text-foreground">Escopo</h2>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="radio"
                name="scope"
                checked={scopeMode === "workspace"}
                onChange={() => setScopeMode("workspace")}
              />
              Padrão do workspace
            </label>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="radio"
                name="scope"
                checked={scopeMode === "agent"}
                onChange={() => setScopeMode("agent")}
              />
              Por agente
            </label>
          </div>

          {scopeMode === "agent" && (
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Agente</label>
              <select
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="input-field max-w-md"
              >
                {editableAgents.length === 0 ? (
                  <option value="">Nenhum agente personalizável</option>
                ) : (
                  editableAgents.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name} — {agent.mode}
                    </option>
                  ))
                )}
              </select>
              {selectedAgent && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Editando a grade exclusiva deste agente.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="glass-card overflow-x-auto p-6">
          <h2 className="mb-4 text-lg font-semibold text-foreground">Grade semanal</h2>
          {loading ? (
            <p className="text-sm text-muted-foreground">Carregando grade…</p>
          ) : (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Ativo</th>
                  <th className="px-3 py-2 font-medium">Dia</th>
                  <th className="px-3 py-2 font-medium">Início</th>
                  <th className="px-3 py-2 font-medium">Fim</th>
                  <th className="px-3 py-2 font-medium">Slot (min)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.weekday} className="border-b border-border/60">
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-border"
                        checked={row.active}
                        onChange={(e) =>
                          updateRow(row.weekday, { active: e.target.checked })
                        }
                      />
                    </td>
                    <td className="px-3 py-3 font-medium text-foreground">{row.label}</td>
                    <td className="px-3 py-3">
                      <input
                        type="time"
                        disabled={!row.active}
                        className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm disabled:opacity-50"
                        value={row.start_time}
                        onChange={(e) =>
                          updateRow(row.weekday, { start_time: e.target.value })
                        }
                      />
                    </td>
                    <td className="px-3 py-3">
                      <input
                        type="time"
                        disabled={!row.active}
                        className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm disabled:opacity-50"
                        value={row.end_time}
                        onChange={(e) =>
                          updateRow(row.weekday, { end_time: e.target.value })
                        }
                      />
                    </td>
                    <td className="px-3 py-3">
                      <input
                        type="number"
                        min={1}
                        disabled={!row.active}
                        placeholder="30"
                        className="w-24 rounded-lg border border-border bg-background px-2 py-1.5 text-sm disabled:opacity-50"
                        value={row.slot_minutes}
                        onChange={(e) =>
                          updateRow(row.weekday, { slot_minutes: e.target.value })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <button
          type="submit"
          disabled={saving || loading || (scopeMode === "agent" && !agentId)}
          className="btn-primary"
        >
          {saving ? "Salvando…" : "Salvar grade"}
        </button>
      </form>
    </>
  );
}
