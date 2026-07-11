"""Unit tests for application logging setup."""

from __future__ import annotations

import logging

from app.core.logging_setup import _configure_logging


def test_configure_logging_agents_namespace_visible() -> None:
    _configure_logging()
    stream_logger = logging.getLogger("agents.channels.voice.stream_session")
    assert stream_logger.getEffectiveLevel() <= logging.INFO
    assert stream_logger.propagate is True
    agents_logger = logging.getLogger("agents")
    assert agents_logger.handlers
    assert agents_logger.propagate is False
    # Re-apply must keep child propagation (uvicorn reload / alembic).
    _configure_logging()
    assert logging.getLogger("agents.channels.voice.stream_session").propagate is True


def test_lazy_agents_logger_created_after_configure_propagates() -> None:
    """Simulates WebSocket lazy import: logger born after _configure_logging()."""
    _configure_logging()
    lazy_name = "agents.channels.voice.stream_session_lazy_test"
    lazy_logger = logging.getLogger(lazy_name)
    assert lazy_logger.propagate is True
    assert not lazy_logger.handlers
    assert lazy_logger.getEffectiveLevel() <= logging.INFO

    agents_logger = logging.getLogger("agents")
    assert agents_logger.handlers

    records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture = _CaptureHandler()
    agents_logger.addHandler(capture)
    try:
        lazy_logger.info("lazy agents logger probe")
        assert records
        assert records[-1].name == lazy_name
        assert records[-1].getMessage() == "lazy agents logger probe"
    finally:
        agents_logger.removeHandler(capture)
