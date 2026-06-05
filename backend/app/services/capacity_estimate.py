"""
Estimativa de capacidade a partir de recursos do container (R-C).

IMPORTANTE: leitura via psutil reflete cgroup/limites do container — é APROXIMAÇÃO.
GPU não é lida no backend; sinal opcional via GET /health do SadTalker.

Unidade: "unidades de recurso" abstratas — combinam CPU e RAM com coeficientes
configuráveis. Cada canal simultâneo consome CHANNEL_COST_* unidades.
MAX_WEIGHTED_CAPACITY pode ser derivado dessa estimativa ou sobrescrito em .env.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import psutil

from app.core.activation_defaults import SUPPORTED_CHANNEL_TYPES, normalize_channel_type
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_cores: float
    cpu_percent_used: float
    cpu_available_ratio: float
    ram_total_mb: float
    ram_available_mb: float
    gpu_signal_available: bool
    gpu_signal_source: str | None
    gpu_device_name: str | None
    container_estimate: bool = True


@dataclass(frozen=True)
class CapacityEstimate:
    resource_units_budget: float
    max_weighted_capacity: int
    channels_if_single_family: dict[str, int]
    channel_costs: dict[str, float]
    notes: list[str]


def channel_costs() -> dict[str, float]:
    return {
        "whatsapp": float(settings.channel_cost_whatsapp),
        "telegram": float(settings.channel_cost_telegram),
        "voice": float(settings.channel_cost_voice),
        "video": float(settings.channel_cost_video),
    }


def _fetch_sadtalker_gpu_signal() -> tuple[bool, str | None, str | None]:
    url = f"{settings.sadtalker_base_url.rstrip('/')}/health"
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return False, "sadtalker_health", None
        data = resp.json()
        gpu = bool(data.get("gpu"))
        device = data.get("device")
        return gpu, "sadtalker_health", str(device) if device else None
    except Exception as exc:
        logger.debug("SadTalker /health indisponível: %s", exc)
        return False, None, None


def read_resources() -> ResourceSnapshot:
    """
    CPU/RAM do processo/container (psutil).

    cpu_available_ratio ≈ (100 - cpu_percent) / 100 após amostra curta.
    """
    cores = float(psutil.cpu_count(logical=True) or 1)
    cpu_pct = float(psutil.cpu_percent(interval=0.2))
    cpu_avail = max(0.0, min(1.0, (100.0 - cpu_pct) / 100.0))

    vm = psutil.virtual_memory()
    ram_total_mb = vm.total / (1024 * 1024)
    ram_avail_mb = vm.available / (1024 * 1024)

    gpu_ok, gpu_src, gpu_name = _fetch_sadtalker_gpu_signal()

    return ResourceSnapshot(
        cpu_cores=cores,
        cpu_percent_used=cpu_pct,
        cpu_available_ratio=cpu_avail,
        ram_total_mb=ram_total_mb,
        ram_available_mb=ram_avail_mb,
        gpu_signal_available=gpu_ok,
        gpu_signal_source=gpu_src,
        gpu_device_name=gpu_name,
    )


def _resource_units_budget(resources: ResourceSnapshot) -> float:
    cpu_units = (
        resources.cpu_available_ratio
        * resources.cpu_cores
        * float(settings.capacity_cpu_units_per_core)
    )
    ram_units = resources.ram_available_mb / float(settings.capacity_mb_per_unit)
    budget = min(cpu_units, ram_units)
    if resources.gpu_signal_available:
        budget *= float(settings.gpu_capacity_boost)
    return max(0.0, budget)


def estimate_capacity(resources: ResourceSnapshot | None = None) -> CapacityEstimate:
    """Capacidade ponderada estimada e canais por família se o mix for 100% um canal."""
    res = resources or read_resources()
    costs = channel_costs()
    budget = _resource_units_budget(res)
    max_cap = max(1, int(budget))

    single_family: dict[str, int] = {}
    for ch in sorted(SUPPORTED_CHANNEL_TYPES):
        cost = costs.get(ch, 1.0)
        single_family[ch] = max(0, int(budget / cost)) if cost > 0 else 0

    notes = [
        "Estimativa baseada em CPU/RAM visíveis ao container (psutil), não no host físico.",
        "Coeficientes CHANNEL_COST_* são unidades abstratas de recurso por canal simultâneo.",
    ]
    if res.gpu_signal_available:
        notes.append(
            f"Sinal GPU via SadTalker /health ({res.gpu_device_name or 'ok'}); "
            f"boost ×{settings.gpu_capacity_boost}."
        )
    else:
        notes.append(
            "Sem sinal GPU no SadTalker — capacidade de vídeo pode ser subestimada."
        )

    return CapacityEstimate(
        resource_units_budget=budget,
        max_weighted_capacity=max_cap,
        channels_if_single_family=single_family,
        channel_costs=costs,
        notes=notes,
    )


def resolve_max_weighted_capacity() -> int:
    """Override manual (.env) ou estimativa derivada do hardware."""
    if settings.max_weighted_capacity_override > 0:
        return int(settings.max_weighted_capacity_override)
    return estimate_capacity().max_weighted_capacity


def estimate_snapshot_dict(resources: ResourceSnapshot) -> dict[str, Any]:
    est = estimate_capacity(resources)
    return {
        "cpu_cores": resources.cpu_cores,
        "cpu_percent_used": resources.cpu_percent_used,
        "cpu_available_ratio": resources.cpu_available_ratio,
        "ram_total_mb": round(resources.ram_total_mb, 1),
        "ram_available_mb": round(resources.ram_available_mb, 1),
        "gpu_signal_available": resources.gpu_signal_available,
        "gpu_signal_source": resources.gpu_signal_source,
        "gpu_device_name": resources.gpu_device_name,
        "container_estimate": resources.container_estimate,
        "resource_units_budget": round(est.resource_units_budget, 2),
        "max_weighted_capacity_estimated": est.max_weighted_capacity,
        "channels_if_single_family": est.channels_if_single_family,
        "channel_costs": est.channel_costs,
        "notes": est.notes,
    }
