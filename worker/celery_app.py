"""Celery application instance."""

import asyncio

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings
from app.services.settings_sync import bootstrap_settings

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
        "worker.tasks.devolutiva_task",
        "worker.tasks.status_sweep",
        "worker.tasks.voice_cleanup",
    ),
    beat_schedule={
        "gerar-devolutivas-diarias": {
            "task": "worker.tasks.devolutiva_task.gerar_devolutivas_diarias",
            "schedule": crontab(hour=0, minute=0),
        },
        "marcar-nao-atendidos": {
            "task": "worker.tasks.status_sweep.marcar_nao_atendidos",
            "schedule": crontab(minute=0),
        },
        "limpar-audios-voz": {
            "task": "worker.tasks.voice_cleanup.limpar_audios_voz",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

# Celery Beat: suba o serviço `celery-beat` no docker-compose para executar o beat_schedule.
# Ex.: celery -A worker.celery_app beat --loglevel=info


@worker_process_init.connect
def _init_worker_settings(**_kwargs) -> None:
    """Seed/load provider settings from DB on each worker child process."""
    asyncio.run(bootstrap_settings())
