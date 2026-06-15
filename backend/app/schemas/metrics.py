"""Pydantic schemas for campaign and lead base metrics."""

from uuid import UUID

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


class AgentMetricsRow(BaseModel):
    agent_id: UUID
    agent_name: str
    mode: str
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


class AgentMetricsResponse(BaseModel):
    agents: list[AgentMetricsRow]


class ChannelQueueMetrics(BaseModel):
    """Métricas de fila receptiva por canal (R-B)."""

    total_enfileirados: int = 0
    total_atendidos: int = 0
    total_abandonados: int = 0
    tempo_medio_espera: float = 0.0
    taxa_abandono: float = 0.0
    nivel_servico: float = 0.0
    tamanho_fila_atual: int = 0


class QueueMetricsResponse(BaseModel):
    """
    Métricas agregadas da fila de atendimento receptivo.

    Abandono (taxa_abandono) aplica-se só a VOZ; sem inbound de voz os valores
    tendem a zero — ver abandono_disponivel_inbound.
    """

    period_days: int = 1
    service_level_target_seconds: int = 20
    total_enfileirados: int = 0
    total_atendidos: int = 0
    total_abandonados: int = 0
    tempo_medio_espera: float = 0.0
    taxa_abandono: float = 0.0
    nivel_servico: float = 0.0
    tamanho_fila_atual: int = 0
    por_canal: dict[str, ChannelQueueMetrics] = Field(default_factory=dict)
    abandono_apenas_voz: bool = True
    abandono_disponivel_inbound: bool = False
