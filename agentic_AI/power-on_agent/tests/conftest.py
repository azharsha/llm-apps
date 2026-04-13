"""Shared pytest fixtures for PoAgent tests.

All fixtures here are available to both unit/ and integration/ test modules.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Minimal board profile fixture ────────────────────────────────────────────

@pytest.fixture()
def minimal_board_profile():
    """Return a minimal BoardProfile-like object for unit tests."""
    profile = MagicMock()
    profile.board_name = "test-board"
    profile.rails = []
    profile.clocks = []
    profile.subsystems = []
    profile.thermal_zones = {}
    return profile


# ── ProbeRunner mock ──────────────────────────────────────────────────────────

class MockRunner:
    """Mock ProbeRunner that returns configurable (rc, output) pairs."""

    def __init__(self, responses: dict[str, tuple[int, str]] | None = None):
        self._responses = responses or {}
        self.commands_called: list[str] = []

    def exec_command(self, cmd: str, timeout: int = 30) -> tuple[int, str]:
        self.commands_called.append(cmd)
        for pattern, result in self._responses.items():
            if pattern in cmd:
                return result
        return (0, "")  # default: success, empty output

    def read_file(self, path: str) -> tuple[int, str]:
        return self._responses.get(path, (0, ""))

    def path_exists(self, path: str) -> bool:
        return path in self._responses

    def glob(self, pattern: str) -> list[str]:
        return []

    def close(self) -> None:
        pass


@pytest.fixture()
def mock_runner():
    """Return a bare MockRunner with no preconfigured responses."""
    return MockRunner()


@pytest.fixture()
def runner_factory():
    """Return a factory that creates MockRunner with given responses."""
    def _make(responses: dict[str, tuple[int, str]]) -> MockRunner:
        return MockRunner(responses)
    return _make


# ── Temp directory fixture ────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


# ── Minimal PoAgentConfig ─────────────────────────────────────────────────────

@pytest.fixture()
def minimal_config():
    """Return a minimal PoAgentConfig for unit tests."""
    from poagent.config import PoAgentConfig
    return PoAgentConfig(
        host="192.168.1.100",
        port=22,
        ssh_user="root",
        board_name="test-board",
        model="claude-sonnet-4-6",
        agent_timeout_seconds=60,
    )


# ── Sample DTS path ──────────────────────────────────────────────────────────

@pytest.fixture()
def sample_dts_path() -> Path:
    """Return path to the sample TGL DTS."""
    p = Path(__file__).parent.parent / "poagent" / "board" / "dts" / "sample_tgl.dts"
    if not p.exists():
        pytest.skip("sample_tgl.dts not found")
    return p


# ── Events for threading tests ────────────────────────────────────────────────

@pytest.fixture()
def pause_event():
    return threading.Event()


@pytest.fixture()
def abort_event():
    return threading.Event()
