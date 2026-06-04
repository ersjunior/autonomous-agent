"""Pydantic schemas for campaign and lead base metrics."""

from pydantic import BaseModel, Field


class MetricsResponse(BaseModel):
    total_leads: int
    total_acionamentos: int
    por_status: dict[str, int] = Field(
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
    por_canal: dict[str, int] = Field(
        default_factory=lambda: {
            "whatsapp": 0,
            "telegram": 0,
            "voice": 0,
        }
    )
    taxa_conversao: float
    taxa_resposta: float
