"""Unit tests — NullPool only in Celery worker processes."""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

from sqlalchemy.pool import NullPool


def test_worker_process_uses_nullpool(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_PROCESS", "1")
    import app.core.database as db_mod

    importlib.reload(db_mod)
    try:
        assert db_mod._is_worker_process() is True
        assert db_mod.engine.pool.__class__ is NullPool
    finally:
        monkeypatch.delenv("WORKER_PROCESS", raising=False)
        importlib.reload(db_mod)


def test_backend_process_uses_queue_pool(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_PROCESS", raising=False)
    import app.core.database as db_mod

    importlib.reload(db_mod)
    assert db_mod._is_worker_process() is False
    assert db_mod.engine.pool.__class__ is not NullPool
