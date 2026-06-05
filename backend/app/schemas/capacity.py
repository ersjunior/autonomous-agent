"""Schemas — análise de capacidade e Erlang C (R-C)."""

from pydantic import BaseModel, Field


class ResourceSection(BaseModel):
    cpu_cores: float
    cpu_percent_used: float
    cpu_available_ratio: float
    ram_total_mb: float
    ram_available_mb: float
    gpu_signal_available: bool
    gpu_signal_source: str | None = None
    gpu_device_name: str | None = None
    container_estimate: bool = True


class CapacityEstimateSection(BaseModel):
    resource_units_budget: float
    max_weighted_capacity_estimated: int
    max_weighted_capacity_effective: int
    max_weighted_capacity_override: int = 0
    channels_if_single_family: dict[str, int] = Field(default_factory=dict)
    channel_costs: dict[str, float] = Field(default_factory=dict)
    channel_weights: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class CapacityUsageSection(BaseModel):
    global_usage: int
    global_max: int
    global_remaining: int
    outbound_weight_bound: int
    receptive_weight_bound: int
    unmapped_usage: int


class ObservedTrafficSection(BaseModel):
    period_days: int
    arrival_rate_per_hour: float
    arrival_count: int
    aht_seconds: float
    aht_sample_count: int
    aht_source: str
    traffic_intensity_erlangs: float


class ErlangSection(BaseModel):
    num_agents: int
    traffic_intensity_erlangs: float
    probability_wait: float
    service_level_predicted: float
    service_level_target: float
    service_level_target_seconds: int
    required_agents_for_target: int
    service_level_at_required: float
    headroom_agents: int
    headroom_volume_percent: float
    analytical_only: bool = True


class CapacityResponse(BaseModel):
    """Capacidade estimada + uso global + dimensionamento Erlang C."""

    resources: ResourceSection
    estimate: CapacityEstimateSection
    usage: CapacityUsageSection
    observed: ObservedTrafficSection
    erlang: ErlangSection
    messaging_channels: list[str] = Field(default_factory=list)
