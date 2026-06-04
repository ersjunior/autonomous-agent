"""Celery application instance."""

import asyncio

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings
from app.core.database import engine
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
        "worker.tasks.activation_scheduler",
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
        # Layer B: retoma leads pendentes de ativações is_running dentro da janela SP.
        # Beat agenda em UTC; is_within_window converte para America/Sao_Paulo.
        "process-active-activations": {
            "task": "worker.tasks.activation_scheduler.process_active_activations",
            "schedule": crontab(minute="*/5"),
        },
    },
)

# Celery Beat: suba o serviço `celery-beat` no docker-compose para executar o beat_schedule.
# Ex.: celery -A worker.celery_app beat --loglevel=info


async def _init_worker_process() -> None:
    """Bootstrap settings and drop pool connections bound to this one-off init loop."""
    await bootstrap_settings()
    await engine.dispose()


@worker_process_init.connect
def _init_worker_settings(**_kwargs) -> None:
    """Seed/load provider settings from DB on each worker child process."""
    asyncio.run(_init_worker_process())
