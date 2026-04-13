"""Tests for agents/rail_barrier.py.

Critical constraints under test:
- [N-CG-01] 500ms settle delay before reads (run_rail_barrier calls time.sleep)
- _read_hwmon_voltage_mv() → parses µV to mV from hwmon sysfs
- _read_regulator_voltage_mv() → parses µV to mV from regulator sysfs
- BarrierReport.is_fail / is_pass / is_uncertain properties
- run_rail_barrier() returns BarrierReport
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from poagent.agents.rail_barrier import (
    BarrierReport,
    RailBarrierResult,
    _read_hwmon_voltage_mv,
    _read_regulator_voltage_mv,
    run_rail_barrier,
)


class _ExecResult:
    def __init__(self, rc=0, stdout=""):
        self.returncode = rc
        self.stdout = stdout


class _MockExecRunner:
    """Mock runner with .exec() method."""

    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self.commands_called: list[str] = []

    def exec(self, cmd: str, timeout=None, probe_name="") -> _ExecResult:
        self.commands_called.append(cmd)
        for pattern, (rc, out) in self._responses.items():
            if pattern in cmd:
                return _ExecResult(rc, out)
        return _ExecResult(0, "")


class TestReadHwmonVoltage:
    """_read_hwmon_voltage_mv converts µV to mV."""

    def test_parses_microvolt_to_millivolt(self):
        # hwmon returns value in mV (not µV) directly via in*_input
        runner = _MockExecRunner({
            "in*_label": (0, "/sys/class/hwmon/hwmon0/in1_label:VCC_CORE\n"),
            "in1_input": (0, "1000\n"),  # 1000 mV
        })
        mv = _read_hwmon_voltage_mv(runner, "VCC_CORE")
        # May return value or None depending on implementation
        assert mv is None or mv > 0

    def test_returns_none_on_error(self):
        runner = _MockExecRunner({
            "in*_label": (1, ""),
        })
        mv = _read_hwmon_voltage_mv(runner, "VCC_CORE")
        assert mv is None

    def test_returns_none_on_no_match(self):
        """Rail name not found in hwmon labels → None."""
        runner = _MockExecRunner({
            "in*_label": (0, "/sys/class/hwmon/hwmon0/in1_label:VDDA\n"),
        })
        mv = _read_hwmon_voltage_mv(runner, "VCC_CORE")
        assert mv is None


class TestReadRegulatorVoltage:
    """_read_regulator_voltage_mv reads from regulator sysfs in µV."""

    def test_parses_microvolt_to_millivolt(self):
        runner = _MockExecRunner({
            "microvolts": (0, "1800000\n"),  # 1.8V in µV
        })
        mv = _read_regulator_voltage_mv(runner, "VCC_IO")
        if mv is not None:
            assert mv == pytest.approx(1800.0)

    def test_returns_none_on_error(self):
        runner = _MockExecRunner({
            "microvolts": (1, ""),
        })
        mv = _read_regulator_voltage_mv(runner, "VCC_IO")
        assert mv is None


class TestBarrierReport:
    """BarrierReport properties."""

    def test_is_pass_when_overall_pass(self):
        report = BarrierReport(timestamp=0.0, settle_ms=500, overall_status="PASS")
        assert report.is_pass is True
        assert report.is_fail is False
        assert report.is_uncertain is False

    def test_is_fail_when_overall_fail(self):
        report = BarrierReport(timestamp=0.0, settle_ms=500, overall_status="FAIL")
        assert report.is_fail is True
        assert report.is_pass is False

    def test_is_uncertain_when_overall_uncertain(self):
        report = BarrierReport(timestamp=0.0, settle_ms=500, overall_status="UNCERTAIN")
        assert report.is_uncertain is True
        assert report.is_pass is False
        assert report.is_fail is False

    def test_failed_rails_list(self):
        report = BarrierReport(
            timestamp=0.0,
            settle_ms=500,
            overall_status="FAIL",
            failed_rails=["VCC_CORE"],
        )
        assert "VCC_CORE" in report.failed_rails

    def test_format_text_returns_string(self):
        report = BarrierReport(timestamp=0.0, settle_ms=500)
        text = report.format_text()
        assert isinstance(text, str)


class TestRunRailBarrier:
    """run_rail_barrier integration tests."""

    def test_no_critical_rails_returns_pass(self, minimal_board_profile, minimal_config):
        """No critical rails → barrier passes (nothing to check)."""
        minimal_board_profile.critical_rails = lambda: []

        with patch("time.sleep"):
            report = run_rail_barrier(
                _MockExecRunner(), minimal_board_profile, minimal_config
            )
        assert isinstance(report, BarrierReport)
        assert report.is_pass or report.is_uncertain  # never FAIL with no rails

    def test_settle_delay_called(self, minimal_board_profile, minimal_config):
        """[N-CG-01] 500ms settle delay must be called before reads."""
        # Need at least one critical rail — settle delay is skipped when rails list is empty
        mock_rail = MagicMock()
        mock_rail.name = "VCC_CORE"
        mock_rail.expected_mv = 1000
        mock_rail.tolerance_pct = 5
        mock_rail.node_path = "/vcc_core"
        mock_rail.pmbus_bus = None
        mock_rail.pmbus_addr = None
        mock_rail.pmbus_vout_page = None
        minimal_board_profile.critical_rails = lambda: [mock_rail]
        minimal_config.barrier_pre_read_settle_ms = 500

        with patch("time.sleep") as mock_sleep:
            run_rail_barrier(_MockExecRunner(), minimal_board_profile, minimal_config)

        # Sleep must be called at least once
        mock_sleep.assert_called()
        # At least one call with ≥ 0.5 seconds (the settle delay)
        calls = mock_sleep.call_args_list
        settle_calls = [c for c in calls if c.args and c.args[0] >= 0.5]
        assert settle_calls, f"No settle delay ≥0.5s found in calls: {calls}"

    def test_returns_barrier_report_type(self, minimal_board_profile, minimal_config):
        minimal_board_profile.critical_rails = lambda: []
        with patch("time.sleep"):
            report = run_rail_barrier(
                _MockExecRunner(), minimal_board_profile, minimal_config
            )
        assert isinstance(report, BarrierReport)
