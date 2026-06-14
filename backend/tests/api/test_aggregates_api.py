"""Camada 3 — aggregates API: capacity, metrics, tunnel, settings."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.app_setting import AppSetting
from app.schemas.tunnel import HealthProbeSection, TunnelStatusResponse
from app.services.capacity_estimate import CapacityEstimate, ResourceSnapshot
from app.services.settings_service import seed_missing_settings

pytestmark = pytest.mark.api

CAPACITY = "/api/v1/capacity"
METRICS = "/api/v1/metrics"
TUNNEL = "/api/v1/tunnel"
SETTINGS = "/api/v1/settings"


def _fake_resources() -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu_cores=4.0,
        cpu_percent_used=25.0,
        cpu_available_ratio=0.75,
        ram_total_mb=8192.0,
        ram_available_mb=4096.0,
        gpu_signal_available=False,
        gpu_signal_source=None,
        gpu_device_name=None,
        container_estimate=True,
    )


def _fake_estimate(_resources=None) -> CapacityEstimate:
    return CapacityEstimate(
        resource_units_budget=100.0,
        max_weighted_capacity=10,
        channels_if_single_family={"whatsapp": 10},
        channel_costs={"whatsapp": 1.0},
        notes=["api-test"],
    )


@pytest.fixture
def mock_capacity_resources(monkeypatch):
    """Hardware e uso Redis determinísticos."""
    monkeypatch.setattr(
        "app.services.capacity_analysis.read_resources",
        lambda: _fake_resources(),
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.estimate_capacity",
        lambda resources=None: _fake_estimate(resources),
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.resolve_max_weighted_capacity",
        lambda: 10,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_global_usage",
        lambda: 2,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_outbound_bound_weight",
        lambda: 1,
    )
    monkeypatch.setattr(
        "app.services.capacity_analysis.current_receptive_bound_weight",
        lambda: 1,
    )


@pytest.fixture
def mock_tunnel_probe(monkeypatch):
    """Evita probe HTTP real em GET /tunnel/status."""

    async def fake_get_tunnel_status(*_args, **_kwargs) -> TunnelStatusResponse:
        return TunnelStatusResponse(
            tunnel_mode="temporary",
            telegram_mode="polling",
            public_base_url_resolved="https://example.test",
            public_base_url_source="env",
            public_base_url_env="https://example.test",
            tunnel_url_file="/tmp/tunnel_url.txt",
            tunnel_url_file_exists=False,
            status="verificado",
            health_probe=HealthProbeSection(
                attempted=True,
                ok=True,
                status_code=200,
                latency_ms=12,
            ),
        )

    monkeypatch.setattr("app.api.v1.tunnel.get_tunnel_status", fake_get_tunnel_status)


@pytest_asyncio.fixture
async def seeded_app_settings(db_session):
    await seed_missing_settings(db_session)
    return db_session


# --- capacity ---


async def test_capacity_requires_auth(client) -> None:
    response = await client.get(CAPACITY)
    assert response.status_code == 401


async def test_capacity_returns_200_with_schema(
    auth_client,
    clean_redis,
    mock_capacity_resources,
) -> None:
    response = await auth_client.get(CAPACITY)
    assert response.status_code == 200
    body = response.json()
    assert body["resources"]["cpu_cores"] == 4.0
    assert body["resources"]["ram_available_mb"] == 4096.0
    assert body["estimate"]["max_weighted_capacity_effective"] == 10
    assert body["usage"]["global_usage"] == 2
    assert body["usage"]["global_max"] == 10
    assert "erlang" in body
    assert "observed" in body
    assert "whatsapp" in body["messaging_channels"]


# --- metrics ---


async def test_metrics_queue_requires_auth(client) -> None:
    response = await client.get(f"{METRICS}/queue")
    assert response.status_code == 401


async def test_metrics_queue_returns_200_with_schema(
    auth_client,
    db_session,
) -> None:
    response = await auth_client.get(f"{METRICS}/queue", params={"days": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["period_days"] == 1
    assert "por_canal" in body
    assert "tamanho_fila_atual" in body
    assert body["abandono_apenas_voz"] is True


@pytest.mark.parametrize("bad_days", [0, 91])
async def test_metrics_queue_invalid_days_returns_422(
    auth_client,
    bad_days: int,
) -> None:
    response = await auth_client.get(f"{METRICS}/queue", params={"days": bad_days})
    assert response.status_code == 422


async def test_metrics_queue_non_int_days_returns_422(auth_client) -> None:
    response = await auth_client.get(f"{METRICS}/queue", params={"days": "abc"})
    assert response.status_code == 422


# --- tunnel ---


async def test_tunnel_status_requires_auth(client) -> None:
    response = await client.get(f"{TUNNEL}/status")
    assert response.status_code == 401


async def test_tunnel_status_returns_200_with_schema(
    auth_client,
    mock_tunnel_probe,
) -> None:
    response = await auth_client.get(f"{TUNNEL}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verificado"
    assert body["public_base_url_resolved"] == "https://example.test"
    assert body["health_probe"]["ok"] is True
    assert body["health_probe"]["status_code"] == 200


# --- settings ---


async def test_settings_get_requires_auth(client) -> None:
    response = await client.get(SETTINGS)
    assert response.status_code == 401


async def test_settings_get_returns_200_dict(
    auth_client,
    seeded_app_settings,
) -> None:
    response = await auth_client.get(SETTINGS)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert "categories" in body
    assert "settings_version" in body
    keys = {
        field["key"]
        for cat in body["categories"]
        for field in cat["fields"]
    }
    assert "rag_top_k" in keys


def _field_value(body: dict, key: str):
    for cat in body["categories"]:
        for field in cat["fields"]:
            if field["key"] == key:
                return field["value"]
    return None


async def test_settings_put_valid_persists(
    auth_client,
    db_session,
    seeded_app_settings,
) -> None:
    response = await auth_client.put(SETTINGS, json={"settings": {"rag_top_k": 7}})
    assert response.status_code == 200
    body = response.json()
    assert _field_value(body, "rag_top_k") == 7

    row = (
        await db_session.execute(
            select(AppSetting).where(AppSetting.key == "rag_top_k")
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.value == "7"


async def test_settings_put_unknown_key_returns_400(
    auth_client,
    seeded_app_settings,
) -> None:
    response = await auth_client.put(
        SETTINGS,
        json={"settings": {"totally_unknown_key": 1}},
    )
    assert response.status_code == 400
    assert "Unknown" in response.json()["detail"]


async def test_settings_put_invalid_body_returns_422(auth_client) -> None:
    response = await auth_client.put(SETTINGS, json={"not_settings": 1})
    assert response.status_code == 422
