"use client";

import { useEffect, useState } from "react";
import { DashboardShell } from "@/components/layout/DashboardShell";
import { getCapacity } from "@/lib/api";
import type { CapacityResponse } from "@/lib/types/capacity";

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  voice: "Voz",
  video: "Vídeo",
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function ahtSourceLabel(source: string): string {
  if (source === "lead_interaction_terminal_span") {
    return "Histórico real (LeadInteraction encerradas)";
  }
  return "Estimativa (DEFAULT_AHT_SECONDS — poucos dados no histórico)";
}

export default function CapacityPage() {
  const [data, setData] = useState<CapacityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getCapacity();
        if (!res.ok) {
          throw new Error("Falha ao carregar capacidade");
        }
        const json = (await res.json()) as CapacityResponse;
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Erro ao carregar capacidade");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const usagePct =
    data && data.usage.global_max > 0
      ? Math.min(100, (data.usage.global_usage / data.usage.global_max) * 100)
      : 0;

  return (
    <DashboardShell>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Capacidade atual</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Estimativa de canais a partir do hardware visível ao container e dimensionamento
          Erlang C com histórico de fila. Não controla o runtime — o teto efetivo em
          produção é o Redis global compartilhado (ativo + receptivo).
        </p>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Carregando...</p>
      ) : error ? (
        <div className="glass-card p-6 text-sm text-red-500">{error}</div>
      ) : !data ? null : (
        <>
          <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200/90">
            <strong>Estimativa, não medição exata.</strong> CPU/RAM vêm do psutil dentro do
            container (cgroup). GPU só por sinal opcional do SadTalker. Coeficientes
            CHANNEL_COST_* são editáveis no <code className="text-xs">.env</code> (somente
            leitura nesta tela).
          </div>

          <section className="mb-8">
            <h2 className="mb-4 text-lg font-semibold text-foreground">Recursos (container)</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">CPU (cores lógicos)</p>
                <p className="mt-2 text-2xl font-semibold">{data.resources.cpu_cores}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Uso {data.resources.cpu_percent_used}% · disponível{" "}
                  {(data.resources.cpu_available_ratio * 100).toFixed(0)}%
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">RAM disponível</p>
                <p className="mt-2 text-2xl font-semibold">
                  {data.resources.ram_available_mb.toFixed(0)} MB
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Total {data.resources.ram_total_mb.toFixed(0)} MB
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Sinal GPU (SadTalker)</p>
                <p className="mt-2 text-2xl font-semibold">
                  {data.resources.gpu_signal_available ? "Sim" : "Não"}
                </p>
                {data.resources.gpu_device_name && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {data.resources.gpu_device_name}
                  </p>
                )}
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">Teto global efetivo</p>
                <p className="mt-2 text-2xl font-semibold text-blue-500">
                  {data.estimate.max_weighted_capacity_effective}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Estimado {data.estimate.max_weighted_capacity_estimated}
                  {data.estimate.max_weighted_capacity_override > 0
                    ? ` · override ${data.estimate.max_weighted_capacity_override}`
                    : ""}
                </p>
              </div>
            </div>
          </section>

          <section className="mb-8">
            <h2 className="mb-4 text-lg font-semibold text-foreground">
              Capacidade estimada por família
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              Orçamento {data.estimate.resource_units_budget.toFixed(1)} unidades abstratas.
              Mix 100% de um canal:
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(data.estimate.channels_if_single_family).map(([ch, n]) => (
                <div key={ch} className="glass-card p-4">
                  <p className="text-sm text-muted-foreground">
                    {CHANNEL_LABELS[ch] ?? ch}
                  </p>
                  <p className="mt-1 text-xl font-semibold">≈ {n} simultâneos</p>
                  <p className="text-xs text-muted-foreground">
                    custo {data.estimate.channel_costs[ch] ?? "—"} · peso runtime{" "}
                    {data.estimate.channel_weights[ch] ?? "—"}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="mb-8">
            <h2 className="mb-4 text-lg font-semibold text-foreground">
              Uso do teto global (runtime)
            </h2>
            <div className="glass-card p-5">
              <div className="mb-2 flex justify-between text-sm">
                <span>
                  {data.usage.global_usage} / {data.usage.global_max} unidades ponderadas
                </span>
                <span>{usagePct.toFixed(0)}%</span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all"
                  style={{ width: `${usagePct}%` }}
                />
              </div>
              <div className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
                <p>
                  <span className="text-muted-foreground">Outbound (ativo):</span>{" "}
                  {data.usage.outbound_weight_bound}
                </p>
                <p>
                  <span className="text-muted-foreground">Receptivo:</span>{" "}
                  {data.usage.receptive_weight_bound}
                </p>
                <p>
                  <span className="text-muted-foreground">Não mapeado:</span>{" "}
                  {data.usage.unmapped_usage}
                </p>
              </div>
            </div>
          </section>

          <section className="mb-8">
            <h2 className="mb-2 text-lg font-semibold text-foreground">
              Erlang C (planejamento)
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              Motor analítico — não bloqueia nem libera filas. Alvo{" "}
              {formatPercent(data.erlang.service_level_target)} em até{" "}
              {data.erlang.service_level_target_seconds}s.
            </p>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">λ (chegadas/h)</p>
                <p className="mt-2 text-2xl font-semibold">
                  {data.observed.arrival_rate_per_hour.toFixed(2)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {data.observed.arrival_count} entradas em {data.observed.period_days}d
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">AHT observado</p>
                <p className="mt-2 text-2xl font-semibold">
                  {data.observed.aht_seconds.toFixed(0)}s
                </p>
                <p className="text-xs text-muted-foreground">
                  {ahtSourceLabel(data.observed.aht_source)} ({data.observed.aht_sample_count}{" "}
                  amostras)
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">
                  Nível de serviço previsto (N={data.erlang.num_agents})
                </p>
                <p className="mt-2 text-2xl font-semibold text-green-500">
                  {formatPercent(data.erlang.service_level_predicted)}
                </p>
                <p className="text-xs text-muted-foreground">
                  A={data.erlang.traffic_intensity_erlangs.toFixed(2)} Erlangs · Pw=
                  {(data.erlang.probability_wait * 100).toFixed(2)}%
                </p>
              </div>
              <div className="glass-card p-5">
                <p className="text-sm text-muted-foreground">
                  Canais para SLA alvo (80/20)
                </p>
                <p className="mt-2 text-2xl font-semibold">
                  {data.erlang.required_agents_for_target}
                </p>
                <p className="text-xs text-muted-foreground">
                  Headroom {data.erlang.headroom_agents} canais · SL@N=
                  {formatPercent(data.erlang.service_level_at_required)}
                </p>
              </div>
            </div>
          </section>

          {data.estimate.notes.length > 0 && (
            <section>
              <h2 className="mb-2 text-lg font-semibold text-foreground">Notas</h2>
              <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
                {data.estimate.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </DashboardShell>
  );
}
