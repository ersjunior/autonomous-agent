export type TunnelStatusLevel =
  | "aguardando"
  | "configurado"
  | "verificado"
  | "inacessivel";

export type PublicBaseUrlSource = "env" | "tunnel_file" | null;

export interface HealthProbeSection {
  attempted: boolean;
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export interface TunnelStatusResponse {
  tunnel_mode: string;
  telegram_mode: string;
  public_base_url_resolved: string | null;
  public_base_url_source: PublicBaseUrlSource;
  public_base_url_env: string | null;
  tunnel_url_file: string;
  tunnel_url_file_exists: boolean;
  tunnel_url_file_raw: string | null;
  env_tunnel_url_diverges: boolean;
  whatsapp_webhook_url: string | null;
  telegram_webhook_url: string | null;
  telegram_webhook_registered: boolean | null;
  telegram_webhook_registered_url: string | null;
  status: TunnelStatusLevel;
  health_probe: HealthProbeSection;
}
