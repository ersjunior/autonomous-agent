"""Application logging setup (restores handlers after Alembic fileConfig)."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def _configure_logging() -> None:
    """Attach stdout handlers to app log namespaces (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.NOTSET)
    handler.setFormatter(
        logging.Formatter("%(levelname)-5.5s [%(name)s] %(message)s")
    )

    for name in ("app", "uvicorn", "sqlalchemy.engine", "agents"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False

    _CONFIGURED = True
