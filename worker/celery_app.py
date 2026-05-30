"""Celery application instance."""

from celery import Celery

from app.core.config import settings

celery = Celery(
    "autonomous_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=(
        "worker.tasks.outbound_campaign",
        "worker.tasks.inbound_handler",
    ),
)
