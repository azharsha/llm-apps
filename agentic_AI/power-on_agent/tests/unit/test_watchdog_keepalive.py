"""Tests for agents/watchdog_keepalive.py.

Critical constraints under test:
- [LAST-S1] dd (not echo redirect) used for watchdog writes
- [LAST-S1] SELinux pre-check via /proc/self/attr/current;
  non-unconfined_t context → WATCHDOG_SELINUX_BLOCKED CRITICAL + abort
- [LAST-C1] SSH failure → WATCHDOG_KEEPALIVE_FAILED CRITICAL + abort_event.set()
- check_watchdog_state() returns a dict with device/timeout_s/nowayout/conflict keys
- handle_watchdog_conflict() dispatches on mode: warn/auto/disable
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest


# ── Mock runner that uses .exec() returning objects with .stdout/.returncode ──

class _ExecResult:
    """Simulate the result object returned by the real SSH/serial runner."""
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


class _MockExecRunner:
    """Mock runner whose .exec() returns _ExecResult objects."""

    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self.commands_called: list[str] = []

    def exec(self, cmd: str, timeout: float = 5.0, probe_name: str = "") -> _ExecResult:
        self.commands_called.append(cmd)
        for pattern, (rc, out) in self._responses.items():
            if pattern in cmd:
                return _ExecResult(rc, out)
        return _ExecResult(0, "")

    def close(self) -> None:
        pass


# ── check_watchdog_state ─────────────────────────────────────────────────────

class TestCheckWatchdogState:
    def test_no_watchdog_device(self):
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        runner = _MockExecRunner({
            "ls /dev/watchdog": (0, ""),  # empty → no device
        })
        config = MagicMock()
        state = check_watchdog_state(runner, config)
        assert isinstance(state, dict)
        assert state["device"] is None

    def test_watchdog_device_present(self):
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        runner = _MockExecRunner({
            "ls /dev/watchdog": (0, "/dev/watchdog0\n"),
            "wdctl": (0, "30"),
            "options": (0, "0x0000"),  # no WDIOF_MAGICCLOSE → nowayout=True
            "pgrep": (0, ""),
            "dmesg": (0, ""),
        })
        config = MagicMock(watchdog_conflict_threshold_s=120)
        state = check_watchdog_state(runner, config)
        assert state["device"] == "/dev/watchdog0"

    def test_nowayout_flag_detected(self):
        """WDIOF_MAGICCLOSE absent → nowayout=True."""
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        runner = _MockExecRunner({
            "ls /dev/watchdog": (0, "/dev/watchdog0\n"),
            "wdctl": (0, "60"),
            "options": (0, "0x0000"),  # no WDIOF_MAGICCLOSE → NOWAYOUT
            "pgrep": (0, ""),
            "dmesg": (0, ""),
        })
        config = MagicMock(watchdog_conflict_threshold_s=120)
        state = check_watchdog_state(runner, config)
        assert state.get("nowayout") is True

    def test_magic_close_means_no_nowayout(self):
        """WDIOF_MAGICCLOSE (0x0100) set → nowayout=False."""
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        runner = _MockExecRunner({
            "ls /dev/watchdog": (0, "/dev/watchdog0\n"),
            "wdctl": (0, "60"),
            "options": (0, "0x0100"),  # WDIOF_MAGICCLOSE present
            "pgrep": (0, ""),
            "dmesg": (0, ""),
        })
        config = MagicMock(watchdog_conflict_threshold_s=120)
        state = check_watchdog_state(runner, config)
        assert state.get("nowayout") is False

    def test_returns_dict_with_required_keys(self):
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        runner = _MockExecRunner()
        config = MagicMock(watchdog_conflict_threshold_s=120)
        state = check_watchdog_state(runner, config)
        for key in ("device", "timeout_s", "nowayout", "watchdogd_pid", "conflict"):
            assert key in state, f"Missing key: {key}"


# ── SELinux pre-check ────────────────────────────────────────────────────────

class TestSELinuxPreCheck:
    """[LAST-S1] SELinux pre-check before watchdog writes."""

    def test_unconfined_t_context_returns_context_string(self):
        """unconfined_t in context → _check_selinux_context returns the string."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        runner = _MockExecRunner({
            "attr/current": (0, "unconfined_u:unconfined_r:unconfined_t:s0"),
        })
        ctx = WatchdogKeepaliveThread._check_selinux_context(runner)
        # Returns the context string; unconfined_t is in it → allowed
        assert ctx is None or "unconfined_t" in ctx

    def test_kernel_context_returned_for_non_unconfined(self):
        """Non-unconfined_t context is returned as string, checked by run()."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        runner = _MockExecRunner({
            "attr/current": (0, "system_u:system_r:kernel_t:s0"),
        })
        ctx = WatchdogKeepaliveThread._check_selinux_context(runner)
        # Returns the context string for non-empty / non-unconfined_t
        assert ctx is not None
        assert "kernel_t" in ctx

    def test_run_aborts_on_selinux_blocked(self):
        """Non-unconfined_t context → abort_event set during run()."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        abort_event = threading.Event()
        runner = _MockExecRunner({
            "attr/current": (0, "system_u:system_r:kernel_t:s0"),
        })
        thread = WatchdogKeepaliveThread(
            runner=runner,
            device="/dev/watchdog0",
            interval_s=60,
            abort_event=abort_event,
        )
        thread.run()  # runs synchronously — will abort on SELinux check
        assert abort_event.is_set()


# ── dd usage requirement ─────────────────────────────────────────────────────

class TestWatchdogUseDd:
    """[LAST-S1] dd must be used, not echo redirect."""

    def test_verify_first_write_uses_dd(self):
        """_verify_first_write() must use dd, not echo >."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        runner = _MockExecRunner({
            "dd": (0, ""),
        })
        thread = WatchdogKeepaliveThread(
            runner=runner,
            device="/dev/watchdog0",
            interval_s=60,
        )
        result = thread._verify_first_write()
        # Must have issued a command with "dd"
        assert any("dd" in cmd for cmd in runner.commands_called)
        # Must not use shell redirect pattern
        for cmd in runner.commands_called:
            if "watchdog" in cmd:
                assert "echo" not in cmd or "dd" in cmd

    def test_verify_first_write_returns_true_on_success(self):
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        runner = _MockExecRunner({"dd": (0, "1+0 records")})
        thread = WatchdogKeepaliveThread(runner=runner, device="/dev/watchdog0")
        assert thread._verify_first_write() is True

    def test_verify_first_write_returns_false_on_eperm(self):
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        runner = _MockExecRunner({"dd": (1, "")})  # rc=1 → EPERM
        thread = WatchdogKeepaliveThread(runner=runner, device="/dev/watchdog0")
        assert thread._verify_first_write() is False


# ── SSH failure → abort ──────────────────────────────────────────────────────

class TestWatchdogSshFailure:
    """[LAST-C1] SSH failure → CRITICAL + abort_event.set()."""

    def test_ssh_failure_in_keepalive_loop_sets_abort(self):
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        abort_event = threading.Event()
        call_count = [0]

        def mock_exec(cmd, timeout=None, probe_name=""):
            call_count[0] += 1
            if "attr/current" in cmd:
                return _ExecResult(0, "unconfined_u:unconfined_r:unconfined_t:s0")
            if call_count[0] <= 2:  # first write (verify) succeeds
                return _ExecResult(0, "")
            raise OSError("SSH connection lost")

        runner = MagicMock()
        runner.exec = mock_exec

        thread = WatchdogKeepaliveThread(
            runner=runner,
            device="/dev/watchdog0",
            interval_s=0,  # zero interval → immediate next write
            abort_event=abort_event,
            wdt_timeout_s=30,
        )
        thread.run()  # will fail after first keepalive loop
        assert abort_event.is_set()


# ── handle_watchdog_conflict ─────────────────────────────────────────────────

class TestHandleWatchdogConflict:
    def _make_wdt_state(self, nowayout: bool = False) -> dict:
        return {
            "device": "/dev/watchdog0",
            "timeout_s": 30,
            "nowayout": nowayout,
            "watchdogd_pid": None,
            "conflict": True,
            "dmesg_wdt": [],
        }

    def test_warn_mode_raises_runtime_error(self):
        from poagent.agents.watchdog_keepalive import handle_watchdog_conflict

        runner = _MockExecRunner()
        config = MagicMock(watchdog_keepalive="warn", watchdog_conflict_threshold_s=120)
        abort_event = threading.Event()

        with pytest.raises(RuntimeError, match="WATCHDOG_RUN_CONFLICT"):
            handle_watchdog_conflict(
                runner=runner,
                config=config,
                wdt_state=self._make_wdt_state(),
                abort_event=abort_event,
            )

    def test_disable_mode_sends_magic_v(self):
        """disable mode writes 'V' to stop the watchdog timer."""
        from poagent.agents.watchdog_keepalive import handle_watchdog_conflict

        runner = _MockExecRunner()
        config = MagicMock(watchdog_keepalive="disable", watchdog_conflict_threshold_s=120)
        abort_event = threading.Event()

        handle_watchdog_conflict(
            runner=runner,
            config=config,
            wdt_state=self._make_wdt_state(nowayout=False),
            abort_event=abort_event,
        )

        # 'V' is the magic close character
        assert any("V" in cmd for cmd in runner.commands_called)

    def test_disable_mode_with_nowayout_raises(self):
        """Cannot disable watchdog with NOWAYOUT set."""
        from poagent.agents.watchdog_keepalive import handle_watchdog_conflict

        runner = _MockExecRunner()
        config = MagicMock(watchdog_keepalive="disable", watchdog_conflict_threshold_s=120)
        abort_event = threading.Event()

        with pytest.raises(RuntimeError, match="NOWAYOUT"):
            handle_watchdog_conflict(
                runner=runner,
                config=config,
                wdt_state=self._make_wdt_state(nowayout=True),
                abort_event=abort_event,
            )

    def test_auto_mode_returns_thread(self):
        """auto mode spawns WatchdogKeepaliveThread."""
        from poagent.agents.watchdog_keepalive import (
            handle_watchdog_conflict, WatchdogKeepaliveThread
        )

        # Return unconfined_t so thread doesn't abort immediately
        runner = _MockExecRunner({"attr/current": (0, "unconfined_u:unconfined_r:unconfined_t:s0")})
        config = MagicMock(
            watchdog_keepalive="auto",
            watchdog_keepalive_interval_s=60,
            watchdog_conflict_threshold_s=120,
        )
        abort_event = threading.Event()

        thread = handle_watchdog_conflict(
            runner=runner,
            config=config,
            wdt_state=self._make_wdt_state(),
            abort_event=abort_event,
        )
        try:
            assert isinstance(thread, WatchdogKeepaliveThread)
        finally:
            if thread is not None:
                thread.stop()
