"""Outbound campaign tasks — modo ATIVO."""

import asyncio
import uuid

from sqlalchemy import select

from agents.channels.telegram.client import send_telegram_message
from agents.channels.whatsapp.twilio_client import send_whatsapp_message
from agents.orchestrator.router import route_message
from app.core.database import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.lead import Lead
from worker.celery_app import celery


def _resolve_user_id(lead: Lead, channel: str) -> str:
    if channel == "telegram":
        telegram_id = lead.extra_data.get("telegram_id") or lead.phone
        if not telegram_id:
            raise ValueError(f"Lead {lead.id} has no telegram_id for Telegram")
        return str(telegram_id)
    if channel == "whatsapp":
        if not lead.phone:
            raise ValueError(f"Lead {lead.id} has no phone for WhatsApp")
        return lead.phone
    raise ValueError(f"Unsupported channel: {channel}")


async def _send_campaign_message(lead_id: str, campaign_id: str, channel: str) -> dict:
    async with AsyncSessionLocal() as session:
        lead_result = await session.execute(
            select(Lead).where(Lead.id == uuid.UUID(lead_id))
        )
        lead = lead_result.scalar_one_or_none()
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        campaign_result = await session.execute(
            select(Campaign).where(Campaign.id == uuid.UUID(campaign_id))
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")

    channel_lower = channel.lower()
    user_id = _resolve_user_id(lead, channel_lower)
    initial_message = lead.extra_data.get(
        "initial_message",
        f"Olá {lead.name}, tudo bem? Sou o assistente virtual da {campaign.name}.",
    )

    result = await route_message(initial_message, channel_lower, user_id)
    response = result.get("response", "")

    if channel_lower == "whatsapp":
        send_whatsapp_message(lead.phone, response)
    elif channel_lower == "telegram":
        await send_telegram_message(user_id, response)

    return {"lead_id": lead_id, "campaign_id": campaign_id, "response": response}


@celery.task(bind=True, max_retries=3)
def send_campaign_message(self, lead_id: str, campaign_id: str, channel: str) -> dict:
    """Envia mensagem ativa para um lead de campanha."""
    try:
        return asyncio.run(_send_campaign_message(lead_id, campaign_id, channel))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc
