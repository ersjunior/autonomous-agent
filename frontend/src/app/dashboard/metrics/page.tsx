"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { getMetricsByAgent, getQueueMetrics } from "@/lib/api";
import {
  AGENT_MODE_LABELS,
  CHANNEL_COLORS,
  CHANNEL_LABELS,
  type AgentMetricsRow,
  type AgentMetricsResponse,
  type QueueMetricsResponse,
} from "@/lib/types/metrics";

const AGENT_TABLE_COLUMNS = [
  "Agente",
  "Modo",
  "Leads",
  "Acionamentos",
  "Taxa de conversão",
  "Taxa de resposta",
] as const;

function formatRatePercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function agentModeLabel(mode: string): string {
  return AGENT_MODE_LABELS[mode] ?? mode;
}

export default function MetricsPage() {
  const [agents, setAgents] = useState<AgentMetricsRow[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [error, setError] = useState("");
  const [queueMetrics, setQueueMetrics] = useState<QueueMetricsResponse | null>(null);
  const [loadingQueueMetrics, setLoadingQueueMetrics] = useState(true);

  const loadAgentMetrics = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setLoadingAgents(true);
    setError("");
    try {
      const res = await getMetricsByAgent();
      if (!res.ok) {
        if (res.status !== 401) {
          setError("Erro ao carregar métricas por agente.");
        }
        setAgents([]);
        return;
      }

      const data: AgentMetricsResponse = await res.json();
      setAgents(data.agents ?? []);
    } catch {
      setError("Erro de conexão ao carregar métricas por agente.");
      setAgents([]);
    } finally {
      setLoadingAgents(false);
    }
  }, []);

  const loadQueueMetrics = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      return;
    }

    setLoadingQueueMetrics(true);
    try {
      const res = await getQueueMetrics(1);
      if (res.ok) {
        setQueueMetrics(await res.json());
      }
    } catch {
      setQueueMetrics(null);
    } finally {
      setLoadingQueueMetrics(false);
    }
  }, []);

  useEffect(() => {
    loadAgentMetrics();
    loadQueueMetrics();
  }, [loadAgentMetrics, loadQueueMetrics]);

  const acionamentosChartData = useMemo(
    () =>
      agents.map((row) => ({
        name: row.agent_name,
        acionamentos: row.total_acionamentos,
        fill: row.mode === "ACTIVE" ? "#3b82f6" : "#8b5cf6",
      })),
    [agents],
  );

  const queueChannelChartData = useMemo(() => {
    if (!queueMetrics) {
      return [];
    }

    return Object.entries(queueMetrics.por_canal)
      .filter(([, ch]) => ch.total_atendidos > 0 || ch.total_enfileirados > 0)
      .map(([key, ch]) => ({
        key,
        name: CHANNEL_LABELS[key] ?? key,
        atendidos: ch.total_atendidos,
        enfileirados: ch.total_enfileirados,
        nivel_servico: Math.round(ch.nivel_servico * 1000) / 10,
        fill: CHANNEL_COLORS[key] ?? "#64748b",
      }));
  }, [queueMetrics]);

  return (
    <>
      <PageHeader
        title="Métricas"
        description="Compare desempenho por agente e acompanhe a fila receptiva."
      />

      {error && <Alert>{error}</Alert>}

      <div className="glass-card mb-6 p-4">
        <h2 className="mb-4 text-sm font-semibold text-foreground">Agentes</h2>
        {loadingAgents ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Carregando métricas por agente...
          </p>
        ) : agents.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nenhum agente cadastrado.
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    {AGENT_TABLE_COLUMNS.map((col) => {
                      const alignRight = col !== "Agente" && col !== "Modo";
                      return (
                        <th
                          key={col}
                          className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground ${
                            alignRight ? "text-right" : "text-left"
                          }`}
                        >
                          {col}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {agents.map((row, rowIndex) => (
                    <tr
                      key={row.agent_id}
                      className={`border-b border-border/50 transition hover:bg-accent/40 ${
                        rowIndex % 2 === 1 ? "bg-muted/20" : ""
                      }`}
                    >
                      <td className="max-w-[220px] truncate px-3 py-2.5 font-medium text-foreground">
                        {row.agent_name}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-left text-muted-foreground">
                        {agentModeLabel(row.mode)}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{row.total_leads}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {row.total_acionamentos}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-green-600 dark:text-green-400">
                        {formatRatePercent(row.taxa_conversao)}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-blue-600 dark:text-blue-400">
                        {formatRatePercent(row.taxa_resposta)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {acionamentosChartData.some((d) => d.acionamentos > 0) && (
              <div className="mt-6 border-t border-border pt-6">
                <h3 className="mb-4 text-sm font-semibold text-foreground">
                  Acionamentos por agente
                </h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={acionamentosChartData}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="acionamentos" name="Acionamentos" radius={[6, 6, 0, 0]}>
                      {acionamentosChartData.map((entry) => (
                        <Cell key={entry.name} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </div>

      <section className="mt-10 border-t border-border pt-8">
        <h2 className="mb-2 text-xl font-semibold text-foreground">Fila de atendimento</h2>
        <p className="mb-6 text-sm text-muted-foreground">
          Métricas do atendimento receptivo (últimas 24h). Abandono aplica-se apenas a voz — ainda
          sem inbound de voz, a taxa tende a zero.
        </p>

        {loadingQueueMetrics ? (
          <p className="text-muted-foreground">Carregando métricas da fila...</p>
        ) : !queueMetrics ? (
          <div className="glass-card p-6 text-sm text-muted-foreground">
            Não foi possível carregar as métricas da fila.
          </div>
        ) : (
          <>
            <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Tempo médio de espera</p>
                <p className="mt-2 text-3xl font-semibold text-foreground">
                  {queueMetrics.tempo_medio_espera.toFixed(1)}s
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">
                  Nível de serviço (até {queueMetrics.service_level_target_seconds}s)
                </p>
                <p className="mt-2 text-3xl font-semibold text-green-500">
                  {formatPercent(queueMetrics.nivel_servico)}
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Taxa de abandono</p>
                <p className="mt-2 text-3xl font-semibold text-foreground">
                  {queueMetrics.total_abandonados === 0
                    ? "—"
                    : formatPercent(queueMetrics.taxa_abandono)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {queueMetrics.total_abandonados === 0
                    ? "Sem registros de abandono no período"
                    : "Somente voz"}
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Tamanho da fila (agora)</p>
                <p className="mt-2 text-3xl font-semibold text-foreground">
                  {queueMetrics.tamanho_fila_atual}
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Total atendidos</p>
                <p className="mt-2 text-3xl font-semibold text-blue-500">
                  {queueMetrics.total_atendidos}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {queueMetrics.total_enfileirados} enfileirados
                </p>
              </div>
            </div>

            <div className="glass-card p-5">
              <h3 className="mb-4 text-lg font-semibold text-foreground">Por canal</h3>
              {queueChannelChartData.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Sem atendimentos receptivos registrados no período.
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={queueChannelChartData}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="atendidos" name="Atendidos" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    <Bar
                      dataKey="enfileirados"
                      name="Enfileirados"
                      fill="#94a3b8"
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </>
        )}
      </section>
    </>
  );
}
