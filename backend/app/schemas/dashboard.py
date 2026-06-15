"""Pydantic schemas for dashboard home summary."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardCards(BaseModel):
    agents: int
    active_channels: int
    leads: int
    active_campaigns: int


class DashboardSummaryResponse(BaseModel):
    cards: DashboardCards
    leads_acionados: int
    leads_virgens: int
    tentativas_por_canal: dict[str, int] = Field(
        default_factory=lambda: {
            "whatsapp": 0,
            "telegram": 0,
            "voice": 0,
        }
    )
    tentativas_por_status: dict[str, int] = Field(
        default_factory=lambda: {
            "pendente": 0,
            "acionado": 0,
            "em_andamento": 0,
            "nao_atendido": 0,
            "convertido": 0,
            "recusou": 0,
            "erro": 0,
        }
    )


class DashboardCampaignRow(BaseModel):
    campaign_id: UUID
    campaign_name: str
    leads: int
    data_recebimento: date | None
    data_inicio: date | None
    data_fim: date | None
    tentativas: int
    spin: float
    contato: int
    cpc: int
    sucesso: int
    conversao: float


class DashboardCampaignsResponse(BaseModel):
    campaigns: list[DashboardCampaignRow]
