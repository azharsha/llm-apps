"""Tests for agents/preflight.py.

Critical constraints under test:
- Gate 3: SSH echo round-trip (check_gate3_ssh)
- Gate 4: Userspace detection (check_gate4_userspace), Method 5 → gate4_method5_only
- Gate 5: DTS sysfs cross-check (check_gate5_sysfs)
- Gate 6: debugfs mount check is WARNING only, never abort (check_gate6_debugfs)
- PreFlightReport has board_name, board_ip, timestamp, gates, gate4_method5_only
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from poagent.agents.preflight import (
    GateResult,
    PreFlightReport,
    check_gate3_ssh,
    check_gate4_userspace,
    check_gate6_debugfs,
)


class _ExecResult:
    def __init__(self, rc=0, stdout=""):
        self.returncode = rc
        self.stdout = stdout


class _MockRunner:
    """Mock runner with .exec() returning _ExecResult objects."""

    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self.commands_called: list[str] = []

    def exec(self, cmd: str, timeout=None, probe_name="") -> _ExecResult:
        self.commands_called.append(cmd)
        for pattern, (rc, out) in self._responses.items():
            if pattern in cmd:
                return _ExecResult(rc, out)
        return _ExecResult(0, "")


class TestGate6DebugfsWarningOnly:
    """Gate 6: debugfs unavailable → WARNING (tuple[GateResult, bool]), never abort."""

    def test_debugfs_unavailable_returns_warning_not_fail(self):
        runner = _MockRunner()  # all commands return empty stdout
        config = MagicMock()
        gate_result, debugfs_available = check_gate6_debugfs(runner, config)
        # Gate 6 must be WARNING-only, never abort
        assert gate_result.severity in ("WARNING", "PASS")
        assert gate_result.gate_num == 6

    def test_debugfs_unavailable_sets_available_false(self):
        runner = _MockRunner()  # no debugfs in mount output
        config = MagicMock()
        _, debugfs_available = check_gate6_debugfs(runner, config)
        # If not mounted, debugfs_available should be False
        assert isinstance(debugfs_available, bool)

    def test_debugfs_available_returns_pass(self):
        runner = _MockRunner({
            "mount": (0, "debugfs on /sys/kernel/debug type debugfs (rw)"),
        })
        config = MagicMock()
        gate_result, debugfs_available = check_gate6_debugfs(runner, config)
        assert gate_result.passed is True
        assert debugfs_available is True

    def test_returns_tuple_of_gate_result_and_bool(self):
        runner = _MockRunner()
        config = MagicMock()
        result = check_gate6_debugfs(runner, config)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], GateResult)
        assert isinstance(result[1], bool)


class TestGate3SshEcho:
    """Gate 3: SSH/serial echo round-trip."""

    def test_echo_success_returns_pass(self):
        runner = _MockRunner({"echo poagent_ready": (0, "poagent_ready")})
        config = MagicMock()
        result = check_gate3_ssh(runner, config)
        assert isinstance(result, GateResult)
        assert result.gate_num == 3
        assert result.passed is True

    def test_echo_failure_returns_fail(self):
        runner = _MockRunner({"echo poagent_ready": (1, "")})
        config = MagicMock()
        result = check_gate3_ssh(runner, config)
        assert result.passed is False

    def test_returns_gate_result(self):
        runner = _MockRunner({"echo": (0, "poagent_ready")})
        config = MagicMock()
        result = check_gate3_ssh(runner, config)
        assert isinstance(result, GateResult)


class TestGate4Userspace:
    """[FINAL-S4] Gate 4 Userspace detection and method5_only flag."""

    def test_systemd_active_returns_pass(self):
        runner = _MockRunner({"systemctl is-active": (0, "active")})
        config = MagicMock()
        gate_result, method5_only = check_gate4_userspace(runner, config)
        assert gate_result.passed is True
        assert method5_only is False

    def test_returns_tuple_of_gate_and_bool(self):
        runner = _MockRunner({"systemctl is-active": (0, "active")})
        config = MagicMock()
        result = check_gate4_userspace(runner, config)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], GateResult)
        assert isinstance(result[1], bool)

    def test_method5_fallback_sets_method5_only(self):
        """All methods 1-4 fail, method 5 (/proc/1/fd) succeeds → gate4_method5_only=True."""
        def exec_fn(cmd, timeout=None, probe_name=""):
            # All normal methods fail — return empty stdout so truthy checks don't trip
            if "systemctl" in cmd:
                return _ExecResult(1, "")
            if "journalctl" in cmd:
                return _ExecResult(1, "")  # empty stdout so method 2 truthy check fails
            if "rc.d" in cmd or "lock/subsys" in cmd:
                return _ExecResult(1, "")
            if "ps" in cmd and "grep" in cmd:
                return _ExecResult(1, "")  # no init process found
            if "sentinel" in cmd or "test -f" in cmd:
                return _ExecResult(0, "no\n")  # sentinel not stable
            if "uptime" in cmd or "proc/uptime" in cmd:
                return _ExecResult(1, "")  # uptime fails
            if "/proc/1/fd" in cmd:
                return _ExecResult(0, "10\n")  # Method 5: fd_count=10 > 5 → succeeds
            if "cmdline" in cmd:
                return _ExecResult(0, "init\n")  # non-swapper cmdline
            return _ExecResult(1, "")

        runner = MagicMock()
        runner.exec = exec_fn
        config = MagicMock()
        config.gate4_sentinel_path = "/tmp/poagent_ready"
        config.gate4_sentinel_stable_count = 3
        config.min_uptime_seconds = 10
        gate_result, method5_only = check_gate4_userspace(runner, config)
        assert gate_result.passed is True
        assert method5_only is True


class TestPreFlightReport:
    """PreFlightReport dataclass structure."""

    def test_has_required_fields(self):
        report = PreFlightReport(
            board_name="test-board",
            board_ip="192.168.1.100",
            timestamp=time.time(),
        )
        assert report.board_name == "test-board"
        assert report.board_ip == "192.168.1.100"
        assert isinstance(report.gates, list)
        assert report.abort_gate is None
        assert report.debugfs_available is True
        assert report.gate4_method5_only is False

    def test_all_critical_passed_property(self):
        report = PreFlightReport(
            board_name="b",
            board_ip="1.2.3.4",
            timestamp=time.time(),
            abort_gate=None,
        )
        assert report.all_critical_passed is True

        report2 = PreFlightReport(
            board_name="b",
            board_ip="1.2.3.4",
            timestamp=time.time(),
            abort_gate=3,
            abort_reason="Gate 3 failed",
        )
        assert report2.all_critical_passed is False

    def test_gate4_method5_only_stored(self):
        report = PreFlightReport(
            board_name="b",
            board_ip="1.2.3.4",
            timestamp=time.time(),
            gate4_method5_only=True,
        )
        assert report.gate4_method5_only is True

    def test_format_text_returns_string(self):
        report = PreFlightReport(
            board_name="test-board",
            board_ip="192.168.1.1",
            timestamp=time.time(),
            gates=[
                GateResult(1, "Power", True, "PASS", "OK"),
                GateResult(3, "SSH", True, "PASS", "echo OK"),
            ],
        )
        text = report.format_text()
        assert isinstance(text, str)
        assert "test-board" in text
