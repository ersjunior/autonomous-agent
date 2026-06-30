"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getDashboardCampaigns, getDashboardSummary } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  CHANNEL_COLORS,
  CHANNEL_LABELS,
  STATUS_COLORS,
  STATUS_LABELS,
  STATUS_ORDER,
  type DashboardCampaignRow,
  type DashboardCampaignsResponse,
  type DashboardChannelFilter,
  type DashboardSummaryResponse,
} from "@/lib/types/metrics";

const CHANNEL_FILTER_OPTIONS: { value: DashboardChannelFilter; label: string }[] = [
  { value: null, label: "Todos" },
  { value: "whatsapp", label: CHANNEL_LABELS.whatsapp },
  { value: "telegram", label: CHANNEL_LABELS.telegram },
  { value: "voice", label: CHANNEL_LABELS.voice },
];

const TABLE_COLUMNS = [
  "Campanha",
  "Leads",
  "Acionáveis",
  "Recebimento",
  "Início",
  "Vigência",
  "Tentativas",
  "Spin",
  "Contato",
  "CPC",
  "Recusa",
  "Sucesso",
  "Conversão",
] as const;

const CHART_HEIGHT = 260;
const STATUS_ROW_HEIGHT = 38;

const LEAD_SLICE_COLORS = {
  acionados: "hsl(262 83% 58%)",
  virgens: "hsl(220 9% 46%)",
} as const;

function formatDateBR(value: string | null): string {
  if (!value) {
    return "—";
  }
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) {
    return "—";
  }
  return `${day.padStart(2, "0")}/${month.padStart(2, "0")}/${year}`;
}

function formatSpin(value: number): string {
  return Number.isInteger(value) ? value.toFixed(1) : value.toFixed(2);
}

function formatConversao(fraction: number): string {
  if (fraction <= 0) {
    return "0%";
  }
  const pct = fraction * 100;
  return `${Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(1)}%`;
}

function conversaoTone(fraction: number): string {
  if (fraction >= 0.5) {
    return "font-medium text-green-600 dark:text-green-400";
  }
  if (fraction > 0) {
    return "font-medium text-amber-600 dark:text-amber-400";
  }
  return "text-muted-foreground";
}

function ChartEmpty({ message }: { message: string }) {
  return (
    <div
      className="flex items-center justify-center text-sm text-muted-foreground"
      style={{ height: CHART_HEIGHT }}
    >
      {message}
    </div>
  );
}

function StatusYAxisTick({
  x,
  y,
  payload,
  muted = false,
}: {
  x?: string | number;
  y?: string | number;
  payload?: { value: string };
  muted?: boolean;
}) {
  const xPos = typeof x === "number" ? x : Number(x) || 0;
  const yPos = typeof y === "number" ? y : Number(y) || 0;
  return (
    <text
      x={xPos}
      y={yPos}
      dy={4}
      textAnchor="end"
      fill={muted ? "hsl(var(--muted-foreground))" : "hsl(var(--foreground))"}
      opacity={muted ? 0.55 : 1}
      fontSize={12}
    >
      {payload?.value}
    </text>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [campaigns, setCampaigns] = useState<DashboardCampaignRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [channelFilter, setChannelFilter] = useState<DashboardChannelFilter>(null);
  const hasLoadedRef = useRef(false);

  const loadDashboard = useCallback(async (channel: DashboardChannelFilter) => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    const isRefresh = hasLoadedRef.current;
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");

    try {
      const [summaryRes, campaignsRes] = await Promise.all([
        getDashboardSummary(channel),
        getDashboardCampaigns(channel),
      ]);

      if (!summaryRes.ok || !campaignsRes.ok) {
        setError("Erro ao carregar métricas do dashboard.");
        if (!isRefresh) {
          setSummary(null);
          setCampaigns([]);
        }
        return;
      }

      const [summaryData, campaignsData]: [
        DashboardSummaryResponse,
        DashboardCampaignsResponse,
      ] = await Promise.all([summaryRes.json(), campaignsRes.json()]);

      setSummary(summaryData);
      setCampaigns(campaignsData.campaigns ?? []);
      hasLoadedRef.current = true;
    } catch {
      setError("Erro ao carregar métricas.");
      if (!isRefresh) {
        setSummary(null);
        setCampaigns([]);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard(channelFilter);
  }, [channelFilter, loadDashboard]);

  const cards = useMemo(
    () => [
      {
        label: "Agentes",
        value: summary?.cards.agents ?? 0,
        href: "/dashboard/agents",
      },
      {
        label: "Canais ativos",
        value: summary?.cards.active_channels ?? 0,
        href: "/dashboard/channels",
      },
      {
        label: "Leads cadastrados",
        value: summary?.cards.leads ?? 0,
        href: "/dashboard/leads",
      },
      {
        label: "Campanhas ativas",
        value: summary?.cards.active_campaigns ?? 0,
        href: "/dashboard/campaigns",
      },
    ],
    [summary],
  );

  const leadsDonutData = useMemo(() => {
    if (!summary) {
      return [];
    }
    return [
      {
        key: "acionados",
        name: "Acionados",
        value: summary.leads_acionados,
        fill: LEAD_SLICE_COLORS.acionados,
      },
      {
        key: "virgens",
        name: "Virgens",
        value: summary.leads_virgens,
        fill: LEAD_SLICE_COLORS.virgens,
      },
    ].filter((item) => item.value > 0);
  }, [summary]);

  const leadsDonutTotal = (summary?.leads_acionados ?? 0) + (summary?.leads_virgens ?? 0);

  const channelBarData = useMemo(() => {
    if (!summary) {
      return [];
    }
    return Object.entries(summary.tentativas_por_canal)
      .filter(([, value]) => value > 0)
      .map(([key, value]) => ({
        key,
        name: CHANNEL_LABELS[key] ?? key,
        value,
        fill: CHANNEL_COLORS[key] ?? "#64748b",
      }));
  }, [summary]);

  const statusBarData = useMemo(() => {
    if (!summary) {
      return [];
    }
    return STATUS_ORDER.map((key) => ({
      key,
      name: STATUS_LABELS[key] ?? key,
      value: summary.tentativas_por_status[key] ?? 0,
      fill: STATUS_COLORS[key] ?? "#94a3b8",
    }));
  }, [summary]);

  const statusInteractionsTotal = useMemo(
    () => statusBarData.reduce((sum, row) => sum + row.value, 0),
    [statusBarData],
  );

  const statusChartHeight = STATUS_ORDER.length * STATUS_ROW_HEIGHT;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Visão geral do seu ecossistema multi-agente."
      />

      {error && <Alert>{error}</Alert>}

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Canal
        </span>
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-border/60 bg-card/50 p-1 backdrop-blur-sm">
          {CHANNEL_FILTER_OPTIONS.map((option) => {
            const active = channelFilter === option.value;
            return (
              <button
                key={option.label}
                type="button"
                onClick={() => setChannelFilter(option.value)}
                disabled={loading && !summary}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  active
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        {refreshing && (
          <span className="text-xs text-muted-foreground">Atualizando…</span>
        )}
      </div>

      {loading && !summary ? (
        <p className="text-muted-foreground">Carregando métricas...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-4">
            {cards.map((card) => (
              <Link
                key={card.label}
                href={card.href}
                className="glass-card group flex items-center justify-between gap-3 p-4 transition hover:-translate-y-0.5 hover:shadow-glow"
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-muted-foreground">
                    {card.label}
                  </p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-foreground">
                    {card.value}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-primary">
                  Ir para →
                </span>
              </Link>
            ))}
          </div>

          <div
            className={`mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3 ${refreshing ? "opacity-60" : ""}`}
          >
            <div className="glass-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-foreground">Leads acionados × virgens</h2>
              {leadsDonutTotal === 0 ? (
                <ChartEmpty message="Nenhum lead nas campanhas." />
              ) : (
                <div className="flex items-center gap-3" style={{ height: CHART_HEIGHT }}>
                  <div className="flex w-[4.5rem] shrink-0 flex-col items-end text-right sm:w-20">
                    <span className="text-xs font-medium text-muted-foreground">Acionados</span>
                    <span
                      className="mt-0.5 text-xl font-semibold tabular-nums"
                      style={{ color: LEAD_SLICE_COLORS.acionados }}
                    >
                      {summary?.leads_acionados ?? 0}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1" style={{ height: CHART_HEIGHT }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={leadsDonutData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          innerRadius="58%"
                          outerRadius="88%"
                          startAngle={90}
                          endAngle={450}
                          paddingAngle={leadsDonutData.length > 1 ? 2 : 0}
                          stroke="none"
                          isAnimationActive={false}
                        >
                          {leadsDonutData.map((entry) => (
                            <Cell key={entry.key} fill={entry.fill} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex w-[4.5rem] shrink-0 flex-col items-start text-left sm:w-20">
                    <span className="text-xs font-medium text-muted-foreground">Virgens</span>
                    <span
                      className="mt-0.5 text-xl font-semibold tabular-nums"
                      style={{ color: LEAD_SLICE_COLORS.virgens }}
                    >
                      {summary?.leads_virgens ?? 0}
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div className="glass-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-foreground">Tentativas por canal</h2>
              {channelBarData.length === 0 ? (
                <ChartEmpty message="Sem tentativas registradas." />
              ) : (
                <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
                  <BarChart data={channelBarData}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Bar dataKey="value" name="Tentativas" radius={[6, 6, 0, 0]}>
                      {channelBarData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="glass-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-foreground">
                Interações por status
              </h2>
              {statusInteractionsTotal === 0 ? (
                <ChartEmpty message="Sem interações registradas." />
              ) : (
                <div
                  className="min-w-0 overflow-x-hidden overflow-y-auto"
                  style={{ height: CHART_HEIGHT }}
                >
                  <ResponsiveContainer width="100%" height={statusChartHeight}>
                    <BarChart
                      data={statusBarData}
                      layout="vertical"
                      margin={{ left: 4, right: 8, top: 2, bottom: 2 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" opacity={0.2} horizontal={false} />
                      <XAxis
                        type="number"
                        allowDecimals={false}
                        tick={{ fontSize: 11 }}
                        domain={[0, (dataMax: number) => Math.max(dataMax, 1)]}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={108}
                        tick={(props) => {
                          const row = statusBarData.find(
                            (item) => item.name === props.payload?.value,
                          );
                          return (
                            <StatusYAxisTick
                              x={props.x}
                              y={props.y}
                              payload={props.payload}
                              muted={row ? row.value === 0 : false}
                            />
                          );
                        }}
                      />
                      <Tooltip
                        formatter={(value) => [value, "Interações"]}
                        labelFormatter={(label) => String(label)}
                      />
                      <Bar dataKey="value" name="Interações" radius={[0, 4, 4, 0]} barSize={22}>
                        {statusBarData.map((entry) => (
                          <Cell
                            key={entry.key}
                            fill={entry.fill}
                            fillOpacity={entry.value > 0 ? 1 : 0.35}
                          />
                        ))}
                        <LabelList
                          dataKey="value"
                          position="insideRight"
                          content={({ x, y, width, value, index }) => {
                            if (x == null || y == null || index == null) {
                              return null;
                            }
                            const num = Number(value ?? 0);
                            const barWidth = Number(width ?? 0);
                            return (
                              <text
                                x={Number(x) + Math.max(barWidth - 6, 6)}
                                y={Number(y) + 14}
                                textAnchor="end"
                                fill="hsl(var(--foreground))"
                                opacity={num > 0 ? 1 : 0.45}
                                fontSize={11}
                              >
                                {num}
                              </text>
                            );
                          }}
                        />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          <div className={`glass-card mt-6 p-4 ${refreshing ? "opacity-60" : ""}`}>
            <h2 className="mb-4 text-sm font-semibold text-foreground">Campanhas</h2>
            {campaigns.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Nenhuma campanha ainda.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1100px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border text-left">
                      {TABLE_COLUMNS.map((col) => {
                        const alignRight = !["Campanha", "Recebimento", "Início", "Vigência"].includes(
                          col,
                        );
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
                    {campaigns.map((row, rowIndex) => (
                      <tr
                        key={row.campaign_id}
                        className={`border-b border-border/50 transition hover:bg-accent/40 ${
                          rowIndex % 2 === 1 ? "bg-muted/20" : ""
                        }`}
                      >
                        <td className="max-w-[200px] truncate px-3 py-2.5 font-medium text-foreground">
                          {row.campaign_name}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.leads}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.acionaveis}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-left tabular-nums">
                          {formatDateBR(row.data_recebimento)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-left tabular-nums">
                          {formatDateBR(row.data_inicio)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-left tabular-nums">
                          {formatDateBR(row.data_fim)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.tentativas}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {formatSpin(row.spin)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.contato}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.cpc}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.recusa}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{row.sucesso}</td>
                        <td
                          className={`px-3 py-2.5 text-right tabular-nums ${conversaoTone(row.conversao)}`}
                        >
                          {formatConversao(row.conversao)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
