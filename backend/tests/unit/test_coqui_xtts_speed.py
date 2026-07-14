"""Tests — Coqui XTTS speed default (P3 fine-tuning)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COQUI_APP_CANDIDATES = (
    _REPO_ROOT / "infra" / "docker" / "coqui-tts" / "app.py",
    Path("/app/app.py"),
)


def _coqui_app_source() -> str:
    for path in _COQUI_APP_CANDIDATES:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    pytest.skip("coqui app.py not available (run from repo checkout or coqui container)")


def test_coqui_xtts_speed_default_is_108() -> None:
    source = _coqui_app_source()
    match = re.search(
        r'_env_float\("COQUI_XTTS_SPEED",\s*([0-9.]+)\)',
        source,
    )
    assert match is not None, "COQUI_XTTS_SPEED default not found in coqui app.py"
    assert float(match.group(1)) == pytest.approx(1.08)


def test_coqui_xtts_inference_kwargs_includes_speed() -> None:
    source = _coqui_app_source()
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_xtts_inference_kwargs"
    )
    keys: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            keys.append(node.value)
    assert "speed" in keys
