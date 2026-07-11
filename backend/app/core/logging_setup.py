"""Application logging setup (restores handlers after Alembic fileConfig)."""

from __future__ import annotations

import logging
import sys

_STDOUT_HANDLER: logging.Handler | None = None
_MANAGER = logging.Logger.manager
_ORIGINAL_GET_LOGGER = _MANAGER.getLogger
_AGENTS_LOGGER_HOOK_INSTALLED = False


def _stdout_handler() -> logging.Handler:
    global _STDOUT_HANDLER
    if _STDOUT_HANDLER is None:
        _STDOUT_HANDLER = logging.StreamHandler(sys.stdout)
        _STDOUT_HANDLER.setLevel(logging.NOTSET)
        _STDOUT_HANDLER.setFormatter(
            logging.Formatter("%(levelname)-5.5s [%(name)s] %(message)s")
        )
    return _STDOUT_HANDLER


def _setup_agents_child_logger(logger: logging.Logger) -> None:
    """Ensure lazy ``agents.*`` children propagate to the configured ``agents`` parent."""
    if not logger.name.startswith("agents.") or logger.name == "agents":
        return
    logger.propagate = True
    if logger.handlers:
        logger.handlers.clear()
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)


def _patched_get_logger(name: str) -> logging.Logger:
    logger = _ORIGINAL_GET_LOGGER(name)
    _setup_agents_child_logger(logger)
    return logger


def _install_agents_logger_hook() -> None:
    """Patch Logger.manager so loggers created after startup still propagate to ``agents``."""
    global _AGENTS_LOGGER_HOOK_INSTALLED
    if _AGENTS_LOGGER_HOOK_INSTALLED:
        return
    _MANAGER.getLogger = _patched_get_logger  # type: ignore[method-assign]
    _AGENTS_LOGGER_HOOK_INSTALLED = True


def _configure_logging() -> None:
    """Attach stdout handlers to app log namespaces (safe to call repeatedly)."""
    handler = _stdout_handler()
    _install_agents_logger_hook()

    for name in ("app", "uvicorn", "sqlalchemy.engine", "agents"):
        log = logging.getLogger(name)
        if handler not in log.handlers:
            log.handlers.clear()
            log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False

    # Child loggers (e.g. agents.channels.voice.stream_session) propagate to ``agents``.
    for name, candidate in logging.Logger.manager.loggerDict.items():
        if not name.startswith("agents.") or not isinstance(candidate, logging.Logger):
            continue
        _setup_agents_child_logger(candidate)
