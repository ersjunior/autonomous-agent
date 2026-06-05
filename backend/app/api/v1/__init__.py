"""API v1 routes."""

from fastapi import APIRouter

from app.api.v1 import (
    activation,
    agents,
    auth,
    campaigns,
    capacity,
    channels,
    handoff,
    lead_bases,
    leads,
    metrics,
    monitoring,
    settings,
    tabulacoes,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(activation.router)
api_router.include_router(agents.router)
api_router.include_router(channels.router)
api_router.include_router(lead_bases.router)
api_router.include_router(leads.router)
api_router.include_router(campaigns.router)
api_router.include_router(metrics.router)
api_router.include_router(capacity.router)
api_router.include_router(monitoring.router)
api_router.include_router(handoff.router)
api_router.include_router(settings.router)
api_router.include_router(tabulacoes.router)
