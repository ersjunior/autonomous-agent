"""API v1 routes."""

from fastapi import APIRouter

from app.api.v1 import agents, auth, campaigns, channels, leads, monitoring

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(channels.router)
api_router.include_router(leads.router)
api_router.include_router(campaigns.router)
api_router.include_router(monitoring.router)
