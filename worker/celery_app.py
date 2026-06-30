"""Celery application instance."""

from app.core.config import settings
from app.services.settings_sync import bootstrap_settings
from worker.async_runner import run_celery_async

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

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
        "worker.tasks.receptive_queue",
        "worker.tasks.queue_abandon_sweep",
        "worker.tasks.kb_ingestion",
        "worker.tasks.human_handoff_sweep",
        "worker.tasks.inactivity_sweep",
        "worker.tasks.appointment_reminder_sweep",
        "worker.tasks.appointment_reminder",
        "worker.tasks.voice_inbound_turn",
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
        # R-A: fila receptiva — dequeue FIFO quando libera capacidade global+slot
        "process-receptive-queue": {
            "task": "worker.tasks.receptive_queue.process_receptive_queue",
            "schedule": float(settings.receptive_queue_beat_seconds),
        },
        # R-B: abandono na fila — só VOZ (sem inbound de voz hoje, no-op em mensageria)
        "sweep-queue-abandonment": {
            "task": "worker.tasks.queue_abandon_sweep.sweep_queue_abandonment",
            "schedule": crontab(minute="*/2"),
        },
        # H-2: handoff humano — queue timeout (devolve ao bot) + finalize timeout (NEG:ABANDONO)
        "sweep-human-handoff-timeouts": {
            "task": "worker.tasks.human_handoff_sweep.sweep_human_handoff_timeouts_task",
            "schedule": float(settings.human_handoff_sweep_seconds),
        },
        # Mensageria — inatividade em em_andamento (lifecycle_version >= 1)
        "sweep-messaging-inactivity": {
            "task": "worker.tasks.inactivity_sweep.sweep_messaging_inactivity",
            "schedule": float(settings.inactivity_sweep_seconds),
        },
        # Agendamentos — lembrete antecipado + acionamento na hora (voice/telegram; Fatia 1)
        "sweep-appointment-reminders": {
            "task": "worker.tasks.appointment_reminder_sweep.sweep_appointment_reminders",
            "schedule": float(settings.appointment_reminder_sweep_seconds),
        },
    },
)

# Celery Beat: suba o serviço `celery-beat` no docker-compose para executar o beat_schedule.
# Ex.: celery -A worker.celery_app beat --loglevel=info


async def _init_worker_process() -> None:
    """Bootstrap settings after prefork (pool inherited from parent is discarded on cleanup)."""
    await bootstrap_settings()


@worker_process_init.connect
def _init_worker_settings(**_kwargs) -> None:
    """Seed/load provider settings from DB on each worker child process."""
    run_celery_async(_init_worker_process())
