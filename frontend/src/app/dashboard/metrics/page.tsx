"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiDownload, apiFetch, getCampaignMetrics } from "@/lib/api";
import type { LeadBaseListResponse } from "@/lib/types/leads";
import {
  CHANNEL_COLORS,
  CHANNEL_LABELS,
  STATUS_COLORS,
  STATUS_LABELS,
  type MetricsResponse,
} from "@/lib/types/metrics";

interface Campaign {
  id: string;
  name: string;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function MetricsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [leadBases, setLeadBases] = useState<LeadBaseListResponse["items"]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [selectedBaseId, setSelectedBaseId] = useState("");
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loadingCampaigns, setLoadingCampaigns] = useState(true);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [downloadingDevolutiva, setDownloadingDevolutiva] = useState(false);
  const [error, setError] = useState("");

  const loadCampaigns = useCallback(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    setLoadingCampaigns(true);
    setError("");
    try {
      const res = await apiFetch("/api/v1/campaigns/");
      if (!res.ok) {
        setError("Erro ao carregar campanhas.");
        return;
      }

      const data: Campaign[] = await res.json();
      setCampaigns(data);
      if (data.length > 0) {
        setSelectedCampaignId((current) =>
          data.some((campaign) => campaign.id === current) ? current : data[0].id,
        );
      } else {
        setSelectedCampaignId("");
      }
    } catch {
      setError("Erro de conexão ao carregar campanhas.");
    } finally {
      setLoadingCampaigns(false);
    }
  }, []);

  const loadLeadBases = useCallback(async (campaignId: string) => {
    if (!campaignId) {
      setLeadBases([]);
      setSelectedBaseId("");
      return;
    }

    try {
      const res = await apiFetch("/api/v1/lead-bases/?skip=0&limit=200");
      if (!res.ok) {
        setLeadBases([]);
        return;
      }

      const data: LeadBaseListResponse = await res.json();
      const filtered = data.items.filter((base) => base.campaign_id === campaignId);
      setLeadBases(filtered);
      setSelectedBaseId((current) =>
        filtered.some((base) => base.id === current) ? current : (filtered[0]?.id ?? ""),
      );
    } catch {
      setLeadBases([]);
      setSelectedBaseId("");
    }
  }, []);

  const loadMetrics = useCallback(async (campaignId: string) => {
    if (!campaignId) {
      setMetrics(null);
      return;
    }

    setLoadingMetrics(true);
    setError("");
    try {
      const res = await getCampaignMetrics(campaignId);
      if (!res.ok) {
        setError("Erro ao carregar métricas da campanha.");
        setMetrics(null);
        return;
      }

      setMetrics(await res.json());
    } catch {
      setError("Erro de conexão ao carregar métricas.");
      setMetrics(null);
    } finally {
      setLoadingMetrics(false);
    }
  }, []);

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  useEffect(() => {
    if (selectedCampaignId) {
      loadLeadBases(selectedCampaignId);
      loadMetrics(selectedCampaignId);
    } else {
      setLeadBases([]);
      setSelectedBaseId("");
      setMetrics(null);
    }
  }, [selectedCampaignId, loadLeadBases, loadMetrics]);

  const statusChartData = useMemo(() => {
    if (!metrics) {
      return [];
    }

    return Object.entries(metrics.por_status)
      .filter(([, value]) => value > 0)
      .map(([key, value]) => ({
        key,
        name: STATUS_LABELS[key] ?? key,
        value,
        fill: STATUS_COLORS[key] ?? "#94a3b8",
      }));
  }, [metrics]);

  const channelChartData = useMemo(() => {
    if (!metrics) {
      return [];
    }

    return Object.entries(metrics.por_canal)
      .filter(([, value]) => value > 0)
      .map(([key, value]) => ({
        key,
        name: CHANNEL_LABELS[key] ?? key,
        value,
        fill: CHANNEL_COLORS[key] ?? "#64748b",
      }));
  }, [metrics]);

  async function handleDownloadDevolutiva() {
    if (!selectedBaseId) {
      return;
    }

    setDownloadingDevolutiva(true);
    setError("");
    try {
      await apiDownload(`/api/v1/lead-bases/${selectedBaseId}/devolutiva`);
    } catch {
      setError("Erro ao baixar devolutiva.");
    } finally {
      setDownloadingDevolutiva(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Métricas"
        description="Acompanhe acionamentos, conversões e desempenho por canal."
      />

      {error && <Alert>{error}</Alert>}

      <div className="glass-card mb-6 p-5">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="campaign" className="mb-2 block text-sm font-medium text-foreground">
              Campanha
            </label>
            {loadingCampaigns ? (
              <p className="text-sm text-muted-foreground">Carregando campanhas...</p>
            ) : campaigns.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma campanha cadastrada.</p>
            ) : (
              <select
                id="campaign"
                value={selectedCampaignId}
                onChange={(event) => setSelectedCampaignId(event.target.value)}
                className="input-field"
              >
                {campaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label htmlFor="leadBase" className="mb-2 block text-sm font-medium text-foreground">
              Base de leads (devolutiva)
            </label>
            {leadBases.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma base nesta campanha.</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                <select
                  id="leadBase"
                  value={selectedBaseId}
                  onChange={(event) => setSelectedBaseId(event.target.value)}
                  className="input-field min-w-0 flex-1"
                >
                  {leadBases.map((base) => (
                    <option key={base.id} value={base.id}>
                      {base.data_recebimento} — {base.leads_count} lead(s)
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleDownloadDevolutiva}
                  disabled={!selectedBaseId || downloadingDevolutiva}
                  className="btn-secondary shrink-0"
                >
                  {downloadingDevolutiva ? "Baixando..." : "Baixar devolutiva"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {loadingMetrics ? (
        <p className="text-muted-foreground">Carregando métricas...</p>
      ) : !metrics ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Selecione uma campanha para ver as métricas.
        </div>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="glass-card p-5">
              <p className="text-sm text-muted-foreground">Total de Leads</p>
              <p className="mt-2 text-3xl font-semibold text-foreground">{metrics.total_leads}</p>
            </div>
            <div className="glass-card p-5">
              <p className="text-sm text-muted-foreground">Total Acionamentos</p>
              <p className="mt-2 text-3xl font-semibold text-foreground">
                {metrics.total_acionamentos}
              </p>
            </div>
            <div className="glass-card p-5">
              <p className="text-sm text-muted-foreground">Taxa de Conversão</p>
              <p className="mt-2 text-3xl font-semibold text-green-500">
                {formatPercent(metrics.taxa_conversao)}
              </p>
            </div>
            <div className="glass-card p-5">
              <p className="text-sm text-muted-foreground">Taxa de Resposta</p>
              <p className="mt-2 text-3xl font-semibold text-blue-500">
                {formatPercent(metrics.taxa_resposta)}
              </p>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <h2 className="mb-4 text-lg font-semibold text-foreground">Por status</h2>
              {statusChartData.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sem acionamentos registrados.</p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie
                      data={statusChartData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={110}
                      label={({ name, value }) => `${name}: ${value}`}
                    >
                      {statusChartData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="glass-card p-5">
              <h2 className="mb-4 text-lg font-semibold text-foreground">Por canal</h2>
              {channelChartData.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sem acionamentos por canal.</p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={channelChartData}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="name" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {channelChartData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
