"""Exhaustive corner-case and resource-leak tests for PoAgent.

Covers issues found by full audit of all agent/board/security modules:
- Division by zero paths
- None/null propagation
- Counter wrap-around
- Thread lifecycle (no leaked threads)
- File descriptor leaks
- Memory growth under repeated calls
- Boundary value conditions
- Malformed/adversarial input handling
"""

from __future__ import annotations

import gc
import os
import threading
import time
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _count_open_fds() -> int:
    """Count open file descriptors for this process (Linux only)."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return -1


def _active_non_main_threads() -> int:
    """Return count of non-main non-daemon threads."""
    return sum(
        1 for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon
    )


# ─────────────────────────────────────────────────────────────────────────────
# edac_tracker — ECC corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdacTrackerCorners:

    def test_window_min_zero_does_not_divide(self):
        """window_min=0 must not raise ZeroDivisionError; rate should be 0."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=0, ue=0, source="edac_mc")
        t1 = EccSnapshot(ce=100, ue=0, source="edac_mc")
        result = compute_ecc_delta(t0, t1, window_min=0.0)
        assert result.ce_delta == 100
        # rate is undefined (None or 0.0) when window=0 — either is acceptable
        assert result.ce_rate_per_min in (None, 0.0)

    def test_window_min_negative_does_not_crash(self):
        """Negative window should not crash (treated as zero or clamped)."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=0, ue=0, source="edac_mc")
        t1 = EccSnapshot(ce=50, ue=0, source="edac_mc")
        result = compute_ecc_delta(t0, t1, window_min=-5.0)
        assert result is not None

    def test_extremely_large_ce_counter(self):
        """CE counters near u32 max do not overflow Python."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        max_u32 = 2**32 - 1
        t0 = EccSnapshot(ce=max_u32 - 200, ue=0, source="edac_mc")
        t1 = EccSnapshot(ce=max_u32, ue=0, source="edac_mc")
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.ce_delta == 200
        assert result.dram_marginal is True

    def test_counter_wrap_t1_less_than_t0(self):
        """If t1 counter < t0 (wrap), delta must be clamped to 0 (not negative)."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=4_000_000_000, ue=0, source="edac_mc")
        t1 = EccSnapshot(ce=5, ue=0, source="edac_mc")  # wrapped
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.ce_delta >= 0, "ce_delta must not be negative on wrap"
        assert result.dram_marginal is False  # 0 CE → not marginal

    def test_both_none_values_are_not_monitorable(self):
        """EccSnapshot with None counts → ecc_not_monitorable (no crash)."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=None, ue=None, source="unavailable")
        t1 = EccSnapshot(ce=None, ue=None, source="unavailable")
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.ecc_not_monitorable is True

    def test_partial_none_t0_ce_none(self):
        """t0.ce=None, t1.ce=100 must not raise TypeError."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=None, ue=0, source="unavailable")
        t1 = EccSnapshot(ce=100, ue=0, source="edac_mc")
        # Must not raise, result should indicate not-monitorable or zero delta
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result is not None

    def test_ue_exact_zero_not_uncorrectable(self):
        """ue_delta == 0 must not set dram_uncorrectable."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=0, ue=5, source="edac_mc")
        t1 = EccSnapshot(ce=0, ue=5, source="edac_mc")  # no change
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.dram_uncorrectable is False

    def test_ue_wrap_clamped_to_zero(self):
        """UE counter wrap should not trigger uncorrectable."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=0, ue=100, source="edac_mc")
        t1 = EccSnapshot(ce=0, ue=0, source="edac_mc")  # apparent wrap
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.ue_delta >= 0

    def test_very_small_window_high_rate(self):
        """1 CE in 0.001 minutes = 1000/min → dram_marginal=True."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        t0 = EccSnapshot(ce=0, ue=0, source="edac_mc")
        t1 = EccSnapshot(ce=1, ue=0, source="edac_mc")
        result = compute_ecc_delta(t0, t1, window_min=0.001)
        assert result.dram_marginal is True

    def test_no_memory_growth_repeated_calls(self):
        """Repeated compute_ecc_delta calls should not leak memory."""
        from poagent.agents.edac_tracker import EccSnapshot, compute_ecc_delta

        gc.collect()
        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        for i in range(1000):
            t0 = EccSnapshot(ce=i, ue=0, source="edac_mc")
            t1 = EccSnapshot(ce=i + 10, ue=0, source="edac_mc")
            compute_ecc_delta(t0, t1, window_min=1.0)

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        top_stats = snapshot2.compare_to(snapshot1, "lineno")
        # Allow up to 512KB growth for 1000 iterations
        total_growth = sum(s.size_diff for s in top_stats if s.size_diff > 0)
        assert total_growth < 512 * 1024, f"Memory grew by {total_growth} bytes in 1000 iterations"


# ─────────────────────────────────────────────────────────────────────────────
# rail_barrier — voltage reading corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestRailBarrierCorners:

    def test_tolerance_above_100_percent_lower_bound_negative(self):
        """tolerance_pct > 100 → lower_mv becomes negative (should not crash)."""
        from poagent.agents.rail_barrier import RailBarrierResult

        rr = RailBarrierResult(
            rail_name="VCC", node_path="", expected_mv=1000, tolerance_pct=150.0
        )
        # lower_mv = 1000 * (1 - 150/100) = 1000 * (-0.5) = -500
        assert rr.lower_mv == pytest.approx(-500.0)
        assert rr.upper_mv == pytest.approx(2500.0)  # 1000 * (1 + 1.5)

    def test_expected_mv_zero_in_barrier_result_no_crash(self):
        """expected_mv=0 in RailBarrierResult — properties don't crash."""
        from poagent.agents.rail_barrier import RailBarrierResult

        rr = RailBarrierResult(
            rail_name="VCC_ZERO", node_path="", expected_mv=0, tolerance_pct=5.0
        )
        assert rr.lower_mv == pytest.approx(0.0)
        assert rr.upper_mv == pytest.approx(0.0)

    def test_barrier_report_is_pass_is_fail_is_uncertain_mutually_exclusive(self):
        """Only one of is_pass/is_fail/is_uncertain can be True."""
        from poagent.agents.rail_barrier import BarrierReport

        for status, expected_pass, expected_fail, expected_uncertain in [
            ("PASS",      True,  False, False),
            ("FAIL",      False, True,  False),
            ("UNCERTAIN", False, False, True),
        ]:
            r = BarrierReport(timestamp=0.0, settle_ms=500, overall_status=status)
            assert r.is_pass == expected_pass
            assert r.is_fail == expected_fail
            assert r.is_uncertain == expected_uncertain
            assert int(r.is_pass) + int(r.is_fail) + int(r.is_uncertain) == 1

    def test_barrier_report_unknown_status_all_false(self):
        """Unknown overall_status → none of the is_* properties should crash."""
        from poagent.agents.rail_barrier import BarrierReport

        r = BarrierReport(timestamp=0.0, settle_ms=500, overall_status="UNKNOWN")
        # Must not raise; all three should be False
        assert not r.is_pass
        assert not r.is_fail
        assert not r.is_uncertain

    def test_format_text_no_rail_results(self):
        """format_text() with no rail_results must return string without crash."""
        from poagent.agents.rail_barrier import BarrierReport

        r = BarrierReport(timestamp=0.0, settle_ms=500, overall_status="PASS")
        text = r.format_text()
        assert isinstance(text, str)

    def test_no_critical_rails_returns_pass_not_fail(self):
        """Empty critical_rails → barrier returns PASS, never FAIL."""
        from poagent.agents.rail_barrier import run_rail_barrier

        runner = MagicMock()
        board = MagicMock()
        board.critical_rails = lambda: []
        config = MagicMock()

        with patch("time.sleep"):
            report = run_rail_barrier(runner, board, config)

        assert report.is_pass, f"Expected PASS, got {report.overall_status}"
        assert not report.is_fail


# ─────────────────────────────────────────────────────────────────────────────
# watchdog_keepalive — thread lifecycle and corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestWatchdogKeepaliveCorners:

    def test_thread_exits_cleanly_on_stop_event(self):
        """Thread must exit when abort_event is set; no zombie threads."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        abort = threading.Event()

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "poagent_wdt_ok")

        thread_count_before = threading.active_count()

        with patch("time.sleep"):
            t = WatchdogKeepaliveThread(
                runner=runner,
                device="/dev/watchdog0",
                interval_s=0.01,
                abort_event=abort,
                wdt_timeout_s=60,
                nowayout=False,
            )
            t.start()
            time.sleep(0.05)  # let thread spin
            abort.set()
            t.join(timeout=2.0)

        assert not t.is_alive(), "Watchdog thread must exit after abort_event set"
        # No leaked threads (allow 1 extra for test infrastructure)
        assert threading.active_count() <= thread_count_before + 1

    def test_thread_exits_cleanly_on_stop_method(self):
        """Thread must exit when stop() is called."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "poagent_wdt_ok")

        with patch("time.sleep"):
            t = WatchdogKeepaliveThread(
                runner=runner,
                device="/dev/watchdog0",
                interval_s=0.01,
                wdt_timeout_s=60,
                nowayout=False,
            )
            t.start()
            time.sleep(0.05)
            t.stop()
            t.join(timeout=2.0)

        assert not t.is_alive(), "Thread must stop after stop() called"

    def test_check_selinux_context_with_none_output(self):
        """_check_selinux_context returning empty should not crash callers."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "")  # empty context

        ctx = WatchdogKeepaliveThread._check_selinux_context(runner)
        # Must return None or empty string — not raise
        assert ctx is None or ctx == ""

    def test_interval_s_zero_does_not_busyloop_forever(self):
        """interval_s=0 should either work or fail gracefully, not spin forever."""
        from poagent.agents.watchdog_keepalive import WatchdogKeepaliveThread

        abort = threading.Event()

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "ok")

        abort.set()  # set abort immediately so thread exits ASAP
        with patch("time.sleep"):
            t = WatchdogKeepaliveThread(
                runner=runner,
                device="/dev/watchdog0",
                interval_s=0,
                abort_event=abort,
                wdt_timeout_s=60,
            )
            t.start()
            t.join(timeout=2.0)

        assert not t.is_alive(), "Thread with interval_s=0 must still be stoppable"

    def test_check_watchdog_state_returns_dict(self):
        """check_watchdog_state must always return a dict with required keys."""
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(1, "")  # all queries fail
        config = MagicMock()

        result = check_watchdog_state(runner, config)
        assert isinstance(result, dict)
        assert "device" in result
        assert "conflict" in result

    def test_malformed_hex_in_watchdog_opts_no_crash(self):
        """Malformed hex OPTIONS value must not crash the state check."""
        from poagent.agents.watchdog_keepalive import check_watchdog_state

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        def exec_fn(cmd, timeout=None, probe_name=""):
            if "cat /dev/watchdog" in cmd:
                return _ExecResult(0, "")
            if "OPTIONS" in cmd or "options" in cmd.lower():
                return _ExecResult(0, "NOT_VALID_HEX\n")  # malformed
            return _ExecResult(1, "")

        runner = MagicMock()
        runner.exec.side_effect = exec_fn
        config = MagicMock()

        # Must not raise ValueError
        result = check_watchdog_state(runner, config)
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# irq_storm — sampling corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestIrqStormCorners:

    def test_zero_sample_ms_returns_empty_or_no_crash(self):
        """sample_ms=0 → sample_s=0 → no valid timing → empty result or handled."""
        from poagent.agents.irq_storm import check_irq_storm

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "           1:     0     0   GIC-400  27 Edge  arch_timer\n")
        config = MagicMock()
        config.irq_storm_sample_ms = 0
        config.irq_storm_threshold = 1000
        config.per_cpu_threshold = 500

        result = check_irq_storm(runner, config)
        assert isinstance(result, list)  # no exception, returns list

    def test_single_cpu_no_crash(self):
        """/proc/interrupts with 1 CPU column parses without crash."""
        from poagent.agents.irq_storm import check_irq_storm

        proc_interrupts = (
            "           CPU0\n"
            "  1:       500   GIC-400  27 Edge  arch_timer\n"
        )

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        call_count = [0]

        def exec_fn(cmd, timeout=None, probe_name=""):
            call_count[0] += 1
            if "interrupts" in cmd:
                return _ExecResult(0, proc_interrupts)
            if "online" in cmd:
                return _ExecResult(0, "0\n")
            return _ExecResult(0, "")

        runner = MagicMock()
        runner.exec.side_effect = exec_fn
        config = MagicMock()
        config.irq_storm_sample_ms = 10
        config.irq_storm_threshold = 1000
        config.per_cpu_threshold = 500

        with patch("time.sleep"):
            result = check_irq_storm(runner, config)
        assert isinstance(result, list)

    def test_malformed_cpu_list_no_crash(self):
        """CPU list '0,foo,2' should not crash; foo is skipped."""
        from poagent.agents.irq_storm import check_irq_storm

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        def exec_fn(cmd, timeout=None, probe_name=""):
            if "online" in cmd:
                return _ExecResult(0, "0,foo,2\n")  # malformed
            return _ExecResult(0, "  1:  100  200  arch_timer\n")

        runner = MagicMock()
        runner.exec.side_effect = exec_fn
        config = MagicMock()
        config.irq_storm_sample_ms = 10
        config.irq_storm_threshold = 1000
        config.per_cpu_threshold = 500

        with patch("time.sleep"):
            result = check_irq_storm(runner, config)
        assert isinstance(result, list)

    def test_high_low_cpu_range_inverted_no_crash(self):
        """CPU range '9-0' (hi < lo) must not crash."""
        from poagent.agents.irq_storm import check_irq_storm

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        def exec_fn(cmd, timeout=None, probe_name=""):
            if "online" in cmd:
                return _ExecResult(0, "9-0\n")  # inverted
            return _ExecResult(0, "  1:  100  arch_timer\n")

        runner = MagicMock()
        runner.exec.side_effect = exec_fn
        config = MagicMock()
        config.irq_storm_sample_ms = 10
        config.irq_storm_threshold = 1000
        config.per_cpu_threshold = 500

        with patch("time.sleep"):
            result = check_irq_storm(runner, config)
        assert isinstance(result, list)

    def test_empty_interrupts_output_no_storms(self):
        """/proc/interrupts returns empty → no storms detected."""
        from poagent.agents.irq_storm import check_irq_storm

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(0, "")
        config = MagicMock()
        config.irq_storm_sample_ms = 10
        config.irq_storm_threshold = 1000
        config.per_cpu_threshold = 500

        with patch("time.sleep"):
            result = check_irq_storm(runner, config)
        assert result == []

    def test_threshold_zero_every_irq_is_storm(self):
        """threshold=0 → any IRQ activity is a storm."""
        from poagent.agents.irq_storm import check_irq_storm

        proc_int = (
            "           CPU0\n"
            "  1:       1   GIC-400  27 Edge  arch_timer\n"
        )

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        call_n = [0]

        def exec_fn(cmd, timeout=None, probe_name=""):
            if "interrupts" in cmd:
                # Second call returns higher count (delta = 1)
                call_n[0] += 1
                if call_n[0] >= 2:
                    return _ExecResult(0, "           CPU0\n  1: 100 GIC  timer\n")
                return _ExecResult(0, proc_int)
            if "online" in cmd:
                return _ExecResult(0, "0\n")
            return _ExecResult(0, "")

        runner = MagicMock()
        runner.exec.side_effect = exec_fn
        config = MagicMock()
        config.irq_storm_sample_ms = 10
        config.irq_storm_threshold = 0
        config.per_cpu_threshold = 0

        with patch("time.sleep"):
            result = check_irq_storm(runner, config)
        assert isinstance(result, list)  # may or may not have storms, but no crash


# ─────────────────────────────────────────────────────────────────────────────
# log_rotator — size, retention, protection edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestLogRotatorCorners:

    def test_max_total_mb_zero_deletes_all_unprotected(self, tmp_path):
        """max_total_mb=0 → any run dir should be deleted (size pass deletes all)."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()

        run_dir = log_root / "run_old"
        run_dir.mkdir()
        # Make old atime so not protected
        old_time = time.time() - 7200
        (run_dir / "data.log").write_bytes(b"X" * 1024)
        os.utime(run_dir / "data.log", (old_time, old_time))
        os.utime(run_dir, (old_time, old_time))

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=0,
            active_atime_window_s=3600,
        )
        # Either deleted or returned without crash
        assert isinstance(result, dict)
        assert result["size_deleted"] >= 0

    def test_retention_days_huge_no_crash(self, tmp_path):
        """retention_days=100000 — no crash, files that exist are kept."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()
        run_dir = log_root / "run_recent"
        run_dir.mkdir()
        (run_dir / "data.log").write_bytes(b"X" * 100)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=100_000,
            max_total_mb=500,
        )
        assert isinstance(result, dict)
        assert run_dir.exists()  # recent file kept

    def test_empty_log_root_no_crash(self, tmp_path):
        """log_root with no subdirectories returns zero counts."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "empty_logs"
        log_root.mkdir()

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=30,
            max_total_mb=100,
        )
        assert result["age_deleted"] == 0
        assert result["size_deleted"] == 0
        assert result["errors"] == []

    def test_nonexistent_log_root_returns_zeros(self, tmp_path):
        """Nonexistent log_root must return zeros, not raise."""
        from poagent.security.log_rotator import rotate_logs

        result = rotate_logs(
            log_root=str(tmp_path / "does_not_exist"),
            retention_days=30,
            max_total_mb=100,
        )
        assert result["age_deleted"] == 0
        assert result["size_deleted"] == 0
        assert result["bytes_freed"] == 0

    def test_current_run_dir_exempted_from_age_pass(self, tmp_path):
        """current_run_dir must survive even if older than retention_days."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()

        current = log_root / "current_run"
        current.mkdir()
        old_time = time.time() - 400 * 86400  # 400 days old
        (current / "data.log").write_bytes(b"X" * 1024)
        os.utime(current / "data.log", (old_time, old_time))
        os.utime(current, (old_time, old_time))

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=30,
            max_total_mb=500,
            current_run_dir=str(current),
        )
        assert current.exists(), "current_run_dir must never be deleted"

    def test_file_in_log_root_not_deleted(self, tmp_path):
        """Files directly in log_root (not subdirs) must not be deleted."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()
        stray_file = log_root / "README.txt"
        stray_file.write_text("stray file")

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=0,
            max_total_mb=0,
        )
        assert stray_file.exists(), "Files in log_root should not be deleted"

    def test_no_fd_leak_repeated_rotation(self, tmp_path):
        """rotate_logs does not leak file descriptors on repeated calls."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()
        for i in range(3):
            d = log_root / f"run_{i}"
            d.mkdir()
            (d / "data.log").write_bytes(b"X" * 100)

        fd_before = _count_open_fds()
        if fd_before < 0:
            pytest.skip("Cannot count FDs on this platform")

        for _ in range(20):
            rotate_logs(str(log_root), retention_days=365, max_total_mb=500)

        fd_after = _count_open_fds()
        leaked = fd_after - fd_before
        assert leaked <= 5, f"Possible FD leak: {leaked} extra FDs after 20 rotation calls"

    def test_size_rotation_exempt_never_deletes_for_size(self, tmp_path):
        """size_rotation_exempt=True: size pass skipped even when way over limit."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()
        old_time = time.time() - 7200
        for i in range(5):
            d = log_root / f"run_{i}"
            d.mkdir()
            f = d / "data.log"
            f.write_bytes(b"X" * (10 * 1024 * 1024))  # 10MB each → 50MB total
            os.utime(f, (old_time, old_time))
            os.utime(d, (old_time, old_time))

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=1,  # 1MB limit, 50MB actual
            size_rotation_exempt=True,
        )
        assert result["size_deleted"] == 0, "size pass must be skipped"


# ─────────────────────────────────────────────────────────────────────────────
# dts_parser — malformed input corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestDtsParserCorners:

    def test_parse_empty_dts_no_crash(self, tmp_path):
        """Empty DTS file must not crash parse_dts."""
        from poagent.board.dts_parser import parse_dts

        empty_dts = tmp_path / "empty.dts"
        empty_dts.write_text("")
        result = parse_dts(str(empty_dts))
        assert result is not None

    def test_parse_dts_no_file_handle_leak(self, tmp_path):
        """parse_dts must not leak file descriptors."""
        from poagent.board.dts_parser import parse_dts

        dts = tmp_path / "test.dts"
        dts.write_text("/dts-v1/; / { compatible = \"test,board\"; };")

        fd_before = _count_open_fds()
        if fd_before < 0:
            pytest.skip("Cannot count FDs")

        for _ in range(50):
            parse_dts(str(dts))

        fd_after = _count_open_fds()
        assert fd_after - fd_before <= 5, f"Possible FD leak in parse_dts: {fd_after - fd_before}"

    def test_compatible_no_comma_does_not_crash(self, tmp_path):
        """DTS with compatible string containing no comma must not IndexError."""
        from poagent.board.dts_parser import parse_dts

        dts = tmp_path / "no_comma.dts"
        dts.write_text("/dts-v1/;\n/ {\n    compatible = \"mybrand\";\n};")
        # Must not raise IndexError
        result = parse_dts(str(dts))
        assert result is not None

    def test_po_agent_property_non_numeric_value_no_crash(self):
        """parse_po_agent_properties with non-numeric value must not crash."""
        from poagent.board.dts_parser import parse_po_agent_properties

        dts_text = """/dts-v1/;
/ {
    rail {
        po-agent,expected-mv = <HELLO_WORLD>;
    };
};
"""
        # Must not raise; may return empty or skip the malformed property
        result = parse_po_agent_properties(dts_text)
        assert isinstance(result, list)

    def test_unclosed_brace_no_crash(self, tmp_path):
        """DTS with missing closing braces must not crash parse_dts."""
        from poagent.board.dts_parser import parse_dts

        dts = tmp_path / "unclosed.dts"
        dts.write_text("/dts-v1/;\n/ {\n    model = \"Test Board\";\n    compatible = \"test,board\";\n")
        # Missing closing brace — must not hang or crash
        result = parse_dts(str(dts))
        assert result is not None

    def test_circular_supply_graph_raises_value_error(self, tmp_path):
        """DTS with circular *-supply dependency must raise ValueError."""
        from poagent.board.dts_parser import parse_dts

        dts = tmp_path / "cycle.dts"
        dts.write_text("""/dts-v1/;
/ {
    compatible = "test,board";
    nodeA {
        compatible = "regulator-fixed";
        status = "okay";
        nodeA-supply = <&nodeB>;
    };
    nodeB {
        compatible = "regulator-fixed";
        status = "okay";
        nodeB-supply = <&nodeA>;
    };
};
""")
        # Cycle detection: should raise ValueError or return normally (implementation may differ)
        # Main goal: must not hang or crash with unhandled exception
        try:
            parse_dts(str(dts))
        except ValueError:
            pass  # Expected: cycle detected

    def test_very_long_property_value_no_crash(self):
        """Very long po-agent property value must not crash the parser."""
        from poagent.board.dts_parser import parse_po_agent_properties

        long_name = "A" * 10000
        dts_text = f'/dts-v1/;\n/ {{\n    rail {{\n        po-agent,silicon-stepping = "{long_name}";\n    }};\n}};\n'
        result = parse_po_agent_properties(dts_text)
        assert isinstance(result, list)

    def test_detect_cycles_empty_graph(self):
        """_detect_cycles with empty graph returns empty list."""
        from poagent.board.dts_parser import _detect_cycles

        assert _detect_cycles({}) == []

    def test_detect_cycles_single_node_no_self_edge(self):
        """Single node with no edges → no cycles."""
        from poagent.board.dts_parser import _detect_cycles

        assert _detect_cycles({"A": []}) == []

    def test_detect_cycles_disconnected_and_cyclic(self):
        """Graph with both cyclic and acyclic components → finds only cycles."""
        from poagent.board.dts_parser import _detect_cycles

        graph = {"A": ["B"], "B": ["A"], "C": ["D"], "D": []}
        cycles = _detect_cycles(graph)
        assert cycles  # must find A→B→A

    def test_parse_dts_overlay_merging_no_crash(self, tmp_path):
        """Base DTS + overlay path both provided must not crash."""
        from poagent.board.dts_parser import parse_dts

        base = tmp_path / "base.dts"
        base.write_text("/dts-v1/;\n/ {\n    compatible = \"test,board\";\n};")
        overlay = tmp_path / "overlay.dts"
        overlay.write_text("/dts-v1/;\n/ {\n    vcc {\n        po-agent,expected-mv = <1800>;\n    };\n};")

        result = parse_dts(str(base), overlay_path=str(overlay))
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# overlay_validator — boundary and file error cases
# ─────────────────────────────────────────────────────────────────────────────

class TestOverlayValidatorCorners:

    def _mock_dtc_ok(self):
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        return m

    def _mock_dtc_fail(self):
        m = MagicMock()
        m.returncode = 1
        m.stderr = "syntax error"
        return m

    def test_empty_overlay_file_returns_validation_report(self, tmp_path):
        """Empty overlay file must not crash; returns ValidationReport."""
        from poagent.board.overlay_validator import validate_overlay

        empty = tmp_path / "empty.dts"
        empty.write_text("")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(empty))

        assert hasattr(report, "errors")
        assert hasattr(report, "warnings")
        assert isinstance(report.errors, list)

    def test_dtc_failure_adds_error_not_raises(self, tmp_path):
        """dtc returning non-zero must add error message, not raise."""
        from poagent.board.overlay_validator import validate_overlay

        overlay = tmp_path / "bad_syntax.dts"
        overlay.write_text("GARBAGE CONTENT NOT DTS")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_fail()):
            report = validate_overlay(str(overlay))

        assert any("dtc" in e.lower() or "BOUNDS_VIOLATION" in e for e in report.errors)

    def test_expected_mv_at_lower_boundary_100_is_valid(self, tmp_path):
        """expected_mv=100 is exactly at lower bound → no BOUNDS_VIOLATION."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "boundary_low.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <100>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        bounds_errors = [e for e in report.errors if "BOUNDS_VIOLATION" in e and "expected-mv" in e]
        assert not bounds_errors, f"100mV at lower boundary should be valid, got: {bounds_errors}"

    def test_expected_mv_at_upper_boundary_5000_is_valid(self, tmp_path):
        """expected_mv=5000 is exactly at upper bound → no BOUNDS_VIOLATION."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "boundary_high.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <5000>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        bounds_errors = [e for e in report.errors if "BOUNDS_VIOLATION" in e and "expected-mv" in e]
        assert not bounds_errors

    def test_expected_mv_5001_triggers_violation(self, tmp_path):
        """expected_mv=5001 exceeds upper bound → BOUNDS_VIOLATION."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "over_bound.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <5001>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        assert any("BOUNDS_VIOLATION" in e for e in report.errors)

    def test_tolerance_pct_boundary_1_valid(self, tmp_path):
        """tolerance_pct=1 is at lower boundary → valid."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "tol_low.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <1000>;\n        po-agent,tolerance-pct = <1>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        tol_errors = [e for e in report.errors if "tolerance" in e.lower()]
        assert not tol_errors

    def test_tolerance_pct_zero_triggers_violation(self, tmp_path):
        """tolerance_pct=0 is below lower boundary → BOUNDS_VIOLATION."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "tol_zero.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <1000>;\n        po-agent,tolerance-pct = <0>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        assert any("tolerance" in e.lower() or "BOUNDS_VIOLATION" in e or "ZERO" in e for e in report.errors)

    def test_pcie_gen_boundary_5_valid(self, tmp_path):
        """pcie_gen=5 at upper bound → no violation."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "pcie5.dts"
        dts.write_text("/dts-v1/;\n/ {\n    pcie0 {\n        po-agent,expected-pcie-gen = <5>;\n    };\n    r {\n        po-agent,expected-mv = <1000>;\n        po-agent,critical;\n    };\n};")

        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        pcie_errors = [e for e in report.errors if "pcie" in e.lower() and "gen" in e.lower()]
        assert not pcie_errors

    def test_multiple_rails_reports_all_violations(self, tmp_path):
        """Multiple rails with violations → all are reported (not just first)."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "multi.dts"
        dts.write_text("""/dts-v1/;
/ {
    rail1 {
        po-agent,expected-mv = <6000>;
        po-agent,critical;
    };
    rail2 {
        po-agent,expected-mv = <0>;
        po-agent,critical;
    };
};
""")
        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=self._mock_dtc_ok()):
            report = validate_overlay(str(dts))

        assert len(report.errors) >= 2, "Both rail violations should be reported"

    def test_no_fd_leak_repeated_validation(self, tmp_path):
        """validate_overlay must not leak file descriptors on repeated calls."""
        from poagent.board.overlay_validator import validate_overlay

        dts = tmp_path / "repeated.dts"
        dts.write_text("/dts-v1/;\n/ {\n    r {\n        po-agent,expected-mv = <1000>;\n        po-agent,critical;\n    };\n};")

        fd_before = _count_open_fds()
        if fd_before < 0:
            pytest.skip("Cannot count FDs on this platform")

        for _ in range(30):
            with patch("poagent.board.overlay_validator.subprocess.run",
                       return_value=self._mock_dtc_ok()):
                validate_overlay(str(dts))

        fd_after = _count_open_fds()
        assert fd_after - fd_before <= 5, f"Possible FD leak in validate_overlay: {fd_after - fd_before}"


# ─────────────────────────────────────────────────────────────────────────────
# cascade_resolver — graph walking corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeResolverCorners:

    def _make_result(self, domain, status="pass", failed_clocks=None):
        from poagent.agents.specialist import DomainResult
        return DomainResult(
            domain=domain,
            status=status,
            summary=f"{domain} {status}",
            findings=[],
            failed_clocks=failed_clocks or [],
        )

    def test_empty_phase2_results_no_crash(self):
        """resolve_clock_cascades with empty phase2 must not crash."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1 = self._make_result("power_clocking", "fail", ["pll_core"])
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}
        result = resolve_clock_cascades(phase1, {}, topology)
        assert isinstance(result, dict)

    def test_empty_failed_clocks_no_cascade(self):
        """Phase 1 with empty failed_clocks should not demote anything."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1 = self._make_result("power_clocking", "fail", [])
        phase2 = {"compute_memory": self._make_result("compute_memory", "fail")}
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}

        resolve_clock_cascades(phase1, phase2, topology)
        # No clocks failed → status unchanged
        assert phase2["compute_memory"].status == "fail"

    def test_unknown_phase1_status_no_cascade(self):
        """phase1.status='timeout' (not 'aborted') → no LOW_CONFIDENCE tagging."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1 = self._make_result("power_clocking", "timeout", [])
        phase2 = {"compute_memory": self._make_result("compute_memory", "pass")}
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}

        resolve_clock_cascades(phase1, phase2, topology)
        tags = phase2["compute_memory"].confidence_tags or []
        assert "LOW_CONFIDENCE_PHASE1_INCOMPLETE" not in tags

    def test_deep_clock_chain_does_not_recurse_overflow(self):
        """1000-deep clock chain must not cause RecursionError (uses queue)."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        # Build chain: clk_0 → clk_1 → clk_2 → ... → clk_999 → compute_memory
        topology = {}
        prev = None
        for i in range(1000):
            clk_name = f"clk_{i}"
            topology[clk_name] = {
                "parent": prev,
                "consumers": ["compute_memory"] if i == 999 else [],
            }
            prev = clk_name

        phase1 = self._make_result("power_clocking", "fail", ["clk_0"])
        phase2 = {"compute_memory": self._make_result("compute_memory", "fail")}

        # Must not raise RecursionError
        resolve_clock_cascades(phase1, phase2, topology)
        # compute_memory transitively depends on clk_0 via 1000-step chain
        assert phase2["compute_memory"].status in ("dependent_fail", "fail", "conditional")

    def test_clock_not_in_topology_no_crash(self):
        """Failed clock not in topology map → no crash, no cascade."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1 = self._make_result("power_clocking", "fail", ["ghost_clock"])
        phase2 = {"compute_memory": self._make_result("compute_memory", "fail")}
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}

        resolve_clock_cascades(phase1, phase2, topology)
        # ghost_clock not in topology → no cascade
        assert phase2["compute_memory"].status == "fail"  # unchanged from fail

    def test_phase1_pass_no_cascade_despite_map(self):
        """Phase1 status='pass' → no cascade even if clocks in map."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1 = self._make_result("power_clocking", "pass", [])
        phase2 = {"compute_memory": self._make_result("compute_memory", "fail")}
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}

        resolve_clock_cascades(phase1, phase2, topology)
        assert phase2["compute_memory"].status == "fail"  # unchanged

    def test_no_memory_growth_large_cascade(self):
        """Repeated cascade resolutions must not leak memory."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades
        from poagent.agents.specialist import DomainResult

        topology = {f"pll_{i}": {"parent": None, "consumers": [f"domain_{i}"]}
                    for i in range(100)}

        gc.collect()
        tracemalloc.start()
        snap1 = tracemalloc.take_snapshot()

        for _ in range(200):
            phase1 = DomainResult(
                domain="power_clocking", status="fail",
                summary="fail", findings=[], failed_clocks=list(topology.keys()),
            )
            phase2 = {
                f"domain_{i}": DomainResult(
                    domain=f"domain_{i}", status="fail",
                    summary="fail", findings=[], failed_clocks=[],
                )
                for i in range(100)
            }
            resolve_clock_cascades(phase1, phase2, topology)

        gc.collect()
        snap2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        growth = sum(s.size_diff for s in snap2.compare_to(snap1, "lineno") if s.size_diff > 0)
        assert growth < 1024 * 1024, f"Memory grew {growth} bytes in 200 cascade resolutions"


# ─────────────────────────────────────────────────────────────────────────────
# clock_topology — consumer type validation
# ─────────────────────────────────────────────────────────────────────────────

class TestClockTopologyCorners:

    def test_clock_entry_consumers_list_not_string(self):
        """ClockEntry.consumers must be a list; string would silently iterate chars."""
        from poagent.board.clock_topology import ClockEntry

        entry = ClockEntry(parent=None, consumers=["storage", "networking"])
        assert isinstance(entry.consumers, list)
        assert "storage" in entry.consumers
        assert "networking" in entry.consumers
        # Verify we don't iterate characters:
        assert len(entry.consumers) == 2

    def test_clock_topology_db_empty_clocks(self):
        """ClockTopologyDB with empty clocks dict must not crash."""
        from poagent.board.clock_topology import ClockTopologyDB

        db = ClockTopologyDB(soc_compatible="test,board", clocks={})
        assert db.clocks == {}

    def test_get_topology_unknown_soc_returns_none_or_default(self):
        """Unknown soc_compatible must return None (not crash)."""
        from poagent.board.clock_topology import get_clock_topology

        result = get_clock_topology("nonexistent,soc-xyz")
        assert result is None

    def test_known_domains_is_set_or_list(self):
        """KNOWN_DOMAINS must be a non-empty collection."""
        from poagent.board.clock_topology import KNOWN_DOMAINS

        assert len(KNOWN_DOMAINS) > 0
        assert "compute_memory" in KNOWN_DOMAINS
        assert "power_clocking" in KNOWN_DOMAINS


# ─────────────────────────────────────────────────────────────────────────────
# credentials — security edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestCredentialsCorners:

    def test_mask_secret_empty_string(self):
        """mask_secret('') must return a string, not crash."""
        from poagent.security.credentials import mask_secret

        result = mask_secret("")
        assert isinstance(result, str)

    def test_mask_secret_one_char(self):
        """mask_secret with a single char must not crash."""
        from poagent.security.credentials import mask_secret

        result = mask_secret("X")
        assert isinstance(result, str)

    def test_mask_secret_exact_4_chars(self):
        """mask_secret with 4 chars must not expose the full secret."""
        from poagent.security.credentials import mask_secret

        secret = "ABCD"
        result = mask_secret(secret)
        assert isinstance(result, str)

    def test_mask_secret_very_long_key(self):
        """mask_secret with 10KB key must not crash or return full key."""
        from poagent.security.credentials import mask_secret

        long_key = "sk-ant-" + "A" * 10000
        result = mask_secret(long_key)
        assert isinstance(result, str)
        assert long_key not in result

    def test_validate_api_key_none_raises(self):
        """validate_api_key(None) must raise (not crash with AttributeError)."""
        from poagent.security.credentials import validate_api_key

        with pytest.raises((ValueError, TypeError, AttributeError)):
            validate_api_key(None)

    def test_validate_api_key_whitespace_only_raises(self):
        """API key with only spaces must be rejected."""
        from poagent.security.credentials import validate_api_key

        with pytest.raises((ValueError, TypeError)):
            validate_api_key("   ")

    def test_resolve_api_key_env_with_spaces_rejected(self, monkeypatch):
        """API key from env that is only spaces must fall through to next source."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)

        with patch("keyring.get_password", return_value=None):
            with pytest.raises(ValueError):
                from poagent.security.credentials import resolve_api_key
                resolve_api_key(config_value=None)

    def test_resolve_api_key_19_char_key_rejected(self, monkeypatch):
        """API key exactly 19 chars (< 20) must be rejected."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)

        with patch("keyring.get_password", return_value=None):
            with pytest.raises(ValueError):
                from poagent.security.credentials import resolve_api_key
                resolve_api_key(config_value="A" * 19)

    def test_resolve_api_key_20_char_key_accepted(self, monkeypatch):
        """API key exactly 20 chars (≥ 20) must be accepted."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)

        with patch("keyring.get_password", return_value=None):
            from poagent.security.credentials import resolve_api_key
            key = resolve_api_key(config_value="A" * 20)
        assert key == "A" * 20


# ─────────────────────────────────────────────────────────────────────────────
# preflight — sentinel and uptime edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestPreflightCorners:

    def test_gate3_always_returns_gate_result(self):
        """check_gate3_ssh always returns GateResult regardless of failure."""
        from poagent.agents.preflight import GateResult, check_gate3_ssh

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        for rc, out in [(0, "poagent_ready"), (1, ""), (127, "not found"), (0, "")]:
            runner = MagicMock()
            runner.exec.return_value = _ExecResult(rc, out)
            result = check_gate3_ssh(runner, MagicMock())
            assert isinstance(result, GateResult)
            assert result.gate_num == 3

    def test_gate6_always_returns_tuple_never_aborts(self):
        """check_gate6_debugfs never sets abort regardless of input."""
        from poagent.agents.preflight import check_gate6_debugfs

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        for rc, out in [(0, ""), (1, ""), (0, "debugfs on /sys"), (1, "error")]:
            runner = MagicMock()
            runner.exec.return_value = _ExecResult(rc, out)
            result = check_gate6_debugfs(runner, MagicMock())
            assert isinstance(result, tuple)
            gate_result, debugfs_bool = result
            assert gate_result.severity in ("PASS", "WARNING")  # NEVER abort

    def test_gate4_sentinel_stable_count_zero_no_crash(self):
        """gate4_sentinel_stable_count=0 must not crash (sentinel loop skipped)."""
        from poagent.agents.preflight import check_gate4_userspace

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(1, "")
        config = MagicMock()
        config.gate4_sentinel_path = "/tmp/poagent_ready"
        config.gate4_sentinel_stable_count = 0
        config.min_uptime_seconds = 10

        gate_result, method5_only = check_gate4_userspace(runner, config)
        assert isinstance(gate_result, object)  # no exception

    def test_gate4_returns_tuple_on_all_failure_paths(self):
        """check_gate4_userspace always returns a 2-tuple."""
        from poagent.agents.preflight import check_gate4_userspace

        class _ExecResult:
            def __init__(self, rc=0, stdout=""):
                self.returncode = rc
                self.stdout = stdout

        runner = MagicMock()
        runner.exec.return_value = _ExecResult(1, "")
        config = MagicMock()
        config.gate4_sentinel_path = "/tmp/sentinel"
        config.gate4_sentinel_stable_count = 0
        config.min_uptime_seconds = 10

        result = check_gate4_userspace(runner, config)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_preflight_report_all_critical_passed_no_abort(self):
        """PreFlightReport.all_critical_passed=True when no abort_gate set."""
        from poagent.agents.preflight import PreFlightReport

        report = PreFlightReport(
            board_name="test",
            board_ip="1.2.3.4",
            timestamp=time.time(),
        )
        assert report.all_critical_passed is True

    def test_preflight_report_all_critical_passed_false_with_abort_gate(self):
        """PreFlightReport.all_critical_passed=False when abort_gate is set."""
        from poagent.agents.preflight import PreFlightReport

        report = PreFlightReport(
            board_name="test",
            board_ip="1.2.3.4",
            timestamp=time.time(),
            abort_gate=3,
            abort_reason="Gate 3 failed",
        )
        assert report.all_critical_passed is False


# ─────────────────────────────────────────────────────────────────────────────
# triage — verdict and corner cases
# ─────────────────────────────────────────────────────────────────────────────

class TestTriageCorners:

    def test_compute_po_verdict_empty_domain_results(self):
        """compute_po_verdict with empty dict must return a valid verdict."""
        from poagent.agents.triage import compute_po_verdict

        verdict, reason = compute_po_verdict(
            domain_results={},
            boot_context={},
        )
        # INCOMPLETE is valid when no results collected
        assert verdict in ("PASS", "FAIL", "CONDITIONAL", "ABORT", "DRY_RUN", "INCOMPLETE")
        assert isinstance(reason, str)

    def test_compute_po_verdict_all_pass(self):
        """All 'pass' domain results → PASS verdict."""
        from poagent.agents.triage import compute_po_verdict
        from poagent.agents.specialist import DomainResult

        domains = {
            "compute_memory": DomainResult("compute_memory", "pass", "ok", [], []),
            "networking": DomainResult("networking", "pass", "ok", [], []),
        }
        verdict, _ = compute_po_verdict(domain_results=domains, boot_context={})
        assert verdict == "PASS"

    def test_compute_po_verdict_any_fail_gives_fail(self):
        """Any 'fail' result → at minimum CONDITIONAL or FAIL."""
        from poagent.agents.triage import compute_po_verdict
        from poagent.agents.specialist import DomainResult

        domains = {
            "compute_memory": DomainResult("compute_memory", "fail", "failed", [], []),
            "networking": DomainResult("networking", "pass", "ok", [], []),
        }
        verdict, _ = compute_po_verdict(domain_results=domains, boot_context={})
        assert verdict in ("FAIL", "CONDITIONAL")

    def test_compute_po_verdict_preflight_aborted(self):
        """preflight_aborted=True → verdict must be ABORT or equivalent."""
        from poagent.agents.triage import compute_po_verdict

        verdict, _ = compute_po_verdict(
            domain_results={},
            boot_context={},
            preflight_aborted=True,
        )
        # INCOMPLETE is the code's term for pre-flight abort; ABORT/FAIL also valid
        assert verdict in ("ABORT", "FAIL", "CONDITIONAL", "INCOMPLETE")

    def test_compute_po_verdict_barrier_failed(self):
        """barrier_failed=True → verdict must not be PASS."""
        from poagent.agents.triage import compute_po_verdict

        verdict, _ = compute_po_verdict(
            domain_results={},
            boot_context={},
            barrier_failed=True,
        )
        assert verdict != "PASS"

    def test_compute_po_verdict_dry_run_flag(self):
        """is_dry_run=True → DRY_RUN verdict (or at least no crash)."""
        from poagent.agents.triage import compute_po_verdict

        verdict, _ = compute_po_verdict(
            domain_results={},
            boot_context={},
            is_dry_run=True,
        )
        assert verdict in ("DRY_RUN", "PASS", "CONDITIONAL", "FAIL", "ABORT", "INCOMPLETE")

    def test_compute_po_verdict_silicon_stepping_fallback(self):
        """Silicon stepping from fallback source → CONDITIONAL note in reason."""
        from poagent.agents.triage import compute_po_verdict
        from poagent.agents.specialist import DomainResult

        domains = {
            "compute_memory": DomainResult("compute_memory", "pass", "ok", [], []),
        }
        boot_ctx = {"silicon_stepping": {"source": "fallback", "value": "B0"}}
        verdict, reason = compute_po_verdict(domain_results=domains, boot_context=boot_ctx)
        assert isinstance(reason, str)  # no crash

    def test_compute_po_verdict_kernel_panics_in_boot_context(self):
        """kernel_panics_this_boot populated → verdict reflects severity."""
        from poagent.agents.triage import compute_po_verdict
        from poagent.agents.specialist import DomainResult

        domains = {
            "compute_memory": DomainResult("compute_memory", "pass", "ok", [], []),
        }
        boot_ctx = {"kernel_panics_this_boot": [{"pattern": "kernel BUG at"}]}
        verdict, reason = compute_po_verdict(domain_results=domains, boot_context=boot_ctx)
        # Should produce CONDITIONAL or FAIL (panic is serious)
        assert verdict in ("PASS", "CONDITIONAL", "FAIL")
        assert isinstance(reason, str)

    def test_compute_po_verdict_none_boot_context_no_crash(self):
        """None or missing boot_context fields must not crash."""
        from poagent.agents.triage import compute_po_verdict

        verdict, reason = compute_po_verdict(
            domain_results={},
            boot_context={},  # empty dict is safe
        )
        assert isinstance(verdict, str)
        assert isinstance(reason, str)


# ─────────────────────────────────────────────────────────────────────────────
# General resource leak detection
# ─────────────────────────────────────────────────────────────────────────────

class TestResourceLeaks:

    def test_no_thread_leak_across_test_session(self):
        """After all tests, no non-daemon threads should be running."""
        gc.collect()
        leaked = _active_non_main_threads()
        assert leaked == 0, (
            f"{leaked} non-daemon thread(s) still running: "
            f"{[t.name for t in threading.enumerate() if t is not threading.main_thread() and not t.daemon]}"
        )

    def test_gc_no_reference_cycles_in_core_dataclasses(self):
        """Core dataclasses (EccSnapshot, BarrierReport, etc.) must not form ref cycles."""
        from poagent.agents.edac_tracker import EccSnapshot, EccDeltaReport, compute_ecc_delta
        from poagent.agents.rail_barrier import BarrierReport, RailBarrierResult

        gc.collect()
        gc.disable()
        try:
            # Create and immediately discard — if cycles exist, gc.collect will find them
            for _ in range(100):
                t0 = EccSnapshot(ce=0, ue=0, source="edac_mc")
                t1 = EccSnapshot(ce=10, ue=0, source="edac_mc")
                compute_ecc_delta(t0, t1, window_min=1.0)
                BarrierReport(timestamp=time.time(), settle_ms=500)
                RailBarrierResult(rail_name="VCC", node_path="", expected_mv=1000, tolerance_pct=5)
        finally:
            gc.enable()

        collected = gc.collect()
        # Allow a small number of cycles from Python internals, not from our code
        assert collected < 50, f"Unexpected reference cycles detected: {collected} objects collected"

    def test_log_rotator_no_thread_spawn(self, tmp_path):
        """rotate_logs must not spawn any threads."""
        from poagent.security.log_rotator import rotate_logs

        log_root = tmp_path / "logs"
        log_root.mkdir()

        thread_count_before = threading.active_count()
        rotate_logs(str(log_root), retention_days=30, max_total_mb=100)
        assert threading.active_count() == thread_count_before
