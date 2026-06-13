"""Schemas — status do túnel Cloudflare e webhooks (TUN-3)."""

from pydantic import BaseModel, Field


class HealthProbeSection(BaseModel):
    attempted: bool = False
    ok: bool = False
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None


class TunnelStatusResponse(BaseModel):
    tunnel_mode: str
    telegram_mode: str
    public_base_url_resolved: str | None = None
    public_base_url_source: str | None = Field(
        default=None,
        description="env | tunnel_file | null",
    )
    public_base_url_env: str | None = None
    tunnel_url_file: str
    tunnel_url_file_exists: bool
    tunnel_url_file_raw: str | None = None
    env_tunnel_url_diverges: bool = False
    whatsapp_webhook_url: str | None = None
    telegram_webhook_url: str | None = None
    telegram_webhook_registered: bool | None = None
    telegram_webhook_registered_url: str | None = None
    status: str = Field(
        description="aguardando | configurado | verificado | inacessivel",
    )
    health_probe: HealthProbeSection = Field(default_factory=HealthProbeSection)
