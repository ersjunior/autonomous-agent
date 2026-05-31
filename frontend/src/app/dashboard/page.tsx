"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";

interface Metrics {
  agents: number;
  activeChannels: number;
  leads: number;
  activeCampaigns: number;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics>({
    agents: 0,
    activeChannels: 0,
    leads: 0,
    activeCampaigns: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadMetrics() {
      const token = localStorage.getItem("access_token");
      if (!token) {
        window.location.href = "/";
        return;
      }

      try {
        const [agentsRes, channelsRes, leadsRes, campaignsRes] =
          await Promise.all([
            apiFetch("/api/v1/agents/"),
            apiFetch("/api/v1/channels/"),
            apiFetch("/api/v1/leads/"),
            apiFetch("/api/v1/campaigns/"),
          ]);

        const [agents, channels, leads, campaigns] = await Promise.all([
          agentsRes.ok ? agentsRes.json() : [],
          channelsRes.ok ? channelsRes.json() : [],
          leadsRes.ok ? leadsRes.json() : [],
          campaignsRes.ok ? campaignsRes.json() : [],
        ]);

        setMetrics({
          agents: Array.isArray(agents) ? agents.length : 0,
          activeChannels: Array.isArray(channels)
            ? channels.filter((c: { is_active: boolean }) => c.is_active).length
            : 0,
          leads: Array.isArray(leads) ? leads.length : 0,
          activeCampaigns: Array.isArray(campaigns)
            ? campaigns.filter((c: { status: string }) => c.status === "active")
                .length
            : 0,
        });
      } catch {
        setError("Erro ao carregar métricas.");
      } finally {
        setLoading(false);
      }
    }

    loadMetrics();
  }, []);

  const cards = [
    { label: "Agentes", value: metrics.agents, href: "/dashboard/agents", accent: "from-violet-500/20 to-violet-500/5" },
    { label: "Canais ativos", value: metrics.activeChannels, href: "/dashboard/channels", accent: "from-emerald-500/20 to-emerald-500/5" },
    { label: "Leads cadastrados", value: metrics.leads, href: "/dashboard/leads", accent: "from-sky-500/20 to-sky-500/5" },
    { label: "Campanhas ativas", value: metrics.activeCampaigns, href: "/dashboard/campaigns", accent: "from-amber-500/20 to-amber-500/5" },
  ];

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Visão geral do seu ecossistema multi-agente."
      />

      {error && <Alert>{error}</Alert>}

      {loading ? (
        <p className="text-muted-foreground">Carregando métricas...</p>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {cards.map((card) => (
            <Link
              key={card.label}
              href={card.href}
              className="glass-card group p-6 transition hover:-translate-y-0.5 hover:shadow-glow"
            >
              <div className={`mb-4 h-1 w-12 rounded-full bg-gradient-to-r ${card.accent}`} />
              <p className="text-sm font-medium text-muted-foreground">{card.label}</p>
              <p className="mt-3 text-4xl font-semibold tracking-tight text-foreground">
                {card.value}
              </p>
              <p className="mt-4 text-xs text-primary opacity-0 transition group-hover:opacity-100">
                Ver detalhes →
              </p>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
