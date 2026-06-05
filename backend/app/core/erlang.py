"""
Erlang C — dimensionamento analítico (R-C).

Motor de planejamento; NÃO controla runtime. Fórmulas clássicas de call center:

  A = λ × AHT   (intensidade de tráfego em Erlangs; λ em contatos/h, AHT em horas)

  Erlang B (prob. bloqueio com N servidores, tráfego A):
    B(N,A) = (A^N / N!) / Σ_{k=0}^{N} (A^k / k!)   [forma recursiva estável]

  Erlang C (prob. espera, A < N):
    C(N,A) = B(N,A) × N / (N − A)

  Nível de serviço (% atendidos em até T segundos, AHT em segundos):
    SL = 1 − C(N,A) × exp(−(N − A) × T / AHT)

  required_agents: menor N ≥ ceil(A) tal que SL(N,A,T,AHT) ≥ alvo.
"""

from __future__ import annotations

import math


def erlang_b(traffic_a: float, num_agents: int) -> float:
    """Probabilidade de bloqueio Erlang B (0..1)."""
    if num_agents <= 0:
        return 0.0
    if traffic_a <= 0:
        return 0.0
    if traffic_a >= num_agents:
        return 1.0

    inv_b = 1.0
    for k in range(1, num_agents + 1):
        inv_b = 1.0 + inv_b * k / traffic_a
    return 1.0 / inv_b


def erlang_c(traffic_a: float, num_agents: int) -> float:
    """
    Probabilidade de espera Erlang C (Pw).

    Requer A < N para estabilidade; se A >= N retorna 1.0.
    """
    if num_agents <= 0:
        return 0.0
    if traffic_a <= 0:
        return 0.0
    if traffic_a >= num_agents:
        return 1.0

    b = erlang_b(traffic_a, num_agents)
    return b * (num_agents / (num_agents - traffic_a))


def service_level(
    num_agents: int,
    traffic_a: float,
    target_seconds: float,
    aht_seconds: float,
) -> float:
    """% de contatos atendidos dentro de ``target_seconds`` (0..1)."""
    if num_agents <= 0 or aht_seconds <= 0 or target_seconds < 0:
        return 0.0
    if traffic_a <= 0:
        return 1.0

    pw = erlang_c(traffic_a, num_agents)
    if pw <= 0:
        return 1.0

    exponent = -(num_agents - traffic_a) * (target_seconds / aht_seconds)
    sl = 1.0 - pw * math.exp(exponent)
    return max(0.0, min(1.0, sl))


def required_agents(
    traffic_a: float,
    target_sl: float,
    target_seconds: float,
    aht_seconds: float,
    *,
    max_search: int = 500,
) -> int:
    """N mínimo de servidores/canais para atingir ``target_sl`` (ex: 0.80)."""
    if traffic_a <= 0:
        return 1
    if aht_seconds <= 0 or target_seconds < 0:
        return max(1, math.ceil(traffic_a))

    start = max(1, math.ceil(traffic_a))
    limit = max(start + 1, start + max_search)
    for n in range(start, limit + 1):
        if service_level(n, traffic_a, target_seconds, aht_seconds) >= target_sl:
            return n
    return limit


def traffic_intensity_erlangs(arrival_rate_per_hour: float, aht_seconds: float) -> float:
    """A = λ × AHT com λ em contatos/h e AHT em segundos."""
    if arrival_rate_per_hour <= 0 or aht_seconds <= 0:
        return 0.0
    aht_hours = aht_seconds / 3600.0
    return arrival_rate_per_hour * aht_hours
