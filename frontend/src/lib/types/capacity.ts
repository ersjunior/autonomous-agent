export interface ResourceSection {
  cpu_cores: number;
  cpu_percent_used: number;
  cpu_available_ratio: number;
  ram_total_mb: number;
  ram_available_mb: number;
  gpu_signal_available: boolean;
  gpu_signal_source: string | null;
  gpu_device_name: string | null;
  container_estimate: boolean;
}

export interface CapacityEstimateSection {
  resource_units_budget: number;
  max_weighted_capacity_estimated: number;
  max_weighted_capacity_effective: number;
  max_weighted_capacity_override: number;
  channels_if_single_family: Record<string, number>;
  channel_costs: Record<string, number>;
  channel_weights: Record<string, number>;
  notes: string[];
}

export interface CapacityUsageSection {
  global_usage: number;
  global_max: number;
  global_remaining: number;
  outbound_weight_bound: number;
  receptive_weight_bound: number;
  unmapped_usage: number;
}

export interface ObservedTrafficSection {
  period_days: number;
  arrival_rate_per_hour: number;
  arrival_count: number;
  aht_seconds: number;
  aht_sample_count: number;
  aht_source: string;
  traffic_intensity_erlangs: number;
}

export interface ErlangSection {
  num_agents: number;
  traffic_intensity_erlangs: number;
  probability_wait: number;
  service_level_predicted: number;
  service_level_target: number;
  service_level_target_seconds: number;
  required_agents_for_target: number;
  service_level_at_required: number;
  headroom_agents: number;
  headroom_volume_percent: number;
  analytical_only: boolean;
}

export interface CapacityResponse {
  resources: ResourceSection;
  estimate: CapacityEstimateSection;
  usage: CapacityUsageSection;
  observed: ObservedTrafficSection;
  erlang: ErlangSection;
  messaging_channels: string[];
}
