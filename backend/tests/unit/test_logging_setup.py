"""Unit tests for application logging setup."""

from __future__ import annotations

import logging

from app.core.logging_setup import _configure_logging


def test_configure_logging_agents_namespace_visible() -> None:
    _configure_logging()
    stream_logger = logging.getLogger("agents.channels.voice.stream_session")
    assert stream_logger.getEffectiveLevel() <= logging.INFO
    agents_logger = logging.getLogger("agents")
    assert agents_logger.handlers
    assert agents_logger.propagate is False
