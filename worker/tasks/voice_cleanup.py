"""Limpeza de MP3s temporários de chamadas outbound."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.core.config import settings
from worker.celery_app import celery

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = 24 * 3600


@celery.task
def limpar_audios_voz() -> dict[str, int]:
    """Remove arquivos .mp3 em voice_audio com mtime maior que 24 horas."""
    root = Path(settings.voice_audio_root)
    if not root.is_dir():
        logger.info("Diretório voice_audio inexistente: %s", root)
        return {"removed": 0}

    cutoff = time.time() - MAX_AGE_SECONDS
    removed = 0
    for path in root.glob("*.mp3"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Não foi possível remover %s: %s", path.name, exc)

    logger.info("Limpeza voice_audio: %s arquivo(s) removido(s)", removed)
    return {"removed": removed}
