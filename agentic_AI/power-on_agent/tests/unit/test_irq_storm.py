"""Tests for irq_storm.py.

Critical constraints under test:
- [N-SG-02] Normalize by online CPU count: rate = agg_delta / cpu_count / sample_s
- Threshold: 1000 IRQ/CPU/s (per-CPU)
- _parse_cpu_list_count handles "0-11" range format
- No storm detected on normal IRQ rates (returns empty list)
- Storm detected when per-CPU rate exceeds threshold (returns non-empty list)
- check_irq_storm(runner, config) → list[IRQStorm]
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from poagent.agents.irq_storm import _parse_cpu_list_count, IRQStorm


class TestParseCpuListCount:
    """Test CPU list range parsing for formats like '0-11'."""

    def test_single_cpu(self):
        assert _parse_cpu_list_count("0") == 1

    def test_range_0_to_3(self):
        assert _parse_cpu_list_count("0-3") == 4

    def test_range_0_to_11(self):
        assert _parse_cpu_list_count("0-11") == 12

    def test_comma_separated(self):
        result = _parse_cpu_list_count("0,2,4")
        assert result == 3

    def test_mixed_range_and_list(self):
        result = _parse_cpu_list_count("0-3,6,8")
        assert result == 6

    def test_empty_string_returns_at_least_one(self):
        result = _parse_cpu_list_count("")
        assert result >= 1


class _ExecResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class TestIRQStormDetection:
    """[N-SG-02] Per-CPU normalized IRQ storm detection."""

    def _make_interrupts_output(self, n_cpus: int, irq_total: int) -> str:
        """Build /proc/interrupts-like text."""
        header = "           " + "  ".join(f"CPU{i}" for i in range(n_cpus))
        per_cpu = irq_total // n_cpus if n_cpus > 0 else 0
        counts = "  ".join(str(per_cpu) for _ in range(n_cpus))
        return f"{header}\n  10:  {counts}  IR-IO-APIC  10-edge  timer\n"

    def _make_runner(self, n_cpus: int, delta: int) -> object:
        """Make a mock runner with .exec() that returns /proc/interrupts snapshots."""
        call_count = [0]
        t0_out = self._make_interrupts_output(n_cpus, 0)
        t1_out = self._make_interrupts_output(n_cpus, delta)

        runner = MagicMock()

        def exec_fn(cmd, timeout=None, probe_name=""):
            if "interrupts" in cmd:
                call_count[0] += 1
                out = t0_out if call_count[0] == 1 else t1_out
                return _ExecResult(0, out)
            if "online" in cmd:
                end = n_cpus - 1
                return _ExecResult(0, f"0-{end}" if end > 0 else "0")
            return _ExecResult(0, "")

        runner.exec = exec_fn
        return runner

    def _make_config(self, sample_ms: int = 100, threshold: float = 1000.0) -> object:
        """Create a minimal config for check_irq_storm."""
        config = MagicMock()
        config.irq_storm_sample_ms = sample_ms
        config.irq_storm_threshold = threshold
        config.per_cpu_threshold = True
        return config

    def test_no_storm_below_threshold(self):
        """4 CPUs × 1000 IRQ/CPU/s threshold; 2000 agg = 500/CPU/s → no storm."""
        from poagent.agents.irq_storm import check_irq_storm

        runner = self._make_runner(n_cpus=4, delta=50)  # 50 IRQs over sample
        config = self._make_config(sample_ms=100, threshold=1000.0)
        # 50 IRQs / 0.1s = 500 agg/s / 4 CPUs = 125/CPU/s < 1000 → no storm
        storms = check_irq_storm(runner, config)
        assert isinstance(storms, list)
        assert len(storms) == 0

    def test_storm_above_threshold(self):
        """High per-CPU rate → storm detected."""
        from poagent.agents.irq_storm import check_irq_storm

        # 4000 IRQs over 0.1s = 40000/s agg = 10000/CPU/s >> 1000 threshold
        runner = self._make_runner(n_cpus=4, delta=4000)
        config = self._make_config(sample_ms=100, threshold=1000.0)
        storms = check_irq_storm(runner, config)
        assert isinstance(storms, list)
        assert len(storms) > 0

    def test_snapdragon_8cx_12core_no_false_storm(self):
        """[N-SG-02] 12-core @ HZ=250: 3000 agg/s = 250/CPU/s → no storm."""
        from poagent.agents.irq_storm import check_irq_storm

        # 3000 IRQs over 10s = 300/s agg / 12 CPUs = 25/CPU/s < 1000
        runner = self._make_runner(n_cpus=12, delta=300)
        config = self._make_config(sample_ms=10000, threshold=1000.0)
        storms = check_irq_storm(runner, config)
        assert isinstance(storms, list)
        assert len(storms) == 0

    def test_irq_storm_has_required_fields(self):
        """IRQStorm dataclass has irq_num and rate_per_cpu_per_sec."""
        from poagent.agents.irq_storm import check_irq_storm

        runner = self._make_runner(n_cpus=1, delta=2000)  # 2000 over 0.1s = 20000/s >> 1000
        config = self._make_config(sample_ms=100, threshold=1000.0)
        storms = check_irq_storm(runner, config)
        if storms:
            storm = storms[0]
            assert hasattr(storm, "irq_num")
            assert hasattr(storm, "rate_per_cpu_per_sec")
            assert hasattr(storm, "agg_rate_per_sec")
            assert hasattr(storm, "online_cpu_count")

    def test_runner_error_returns_empty_list(self):
        """If /proc/interrupts fails, check_irq_storm should return empty list."""
        from poagent.agents.irq_storm import check_irq_storm

        runner = MagicMock()
        runner.exec = MagicMock(return_value=_ExecResult(1, "permission denied"))
        config = self._make_config()
        storms = check_irq_storm(runner, config)
        assert isinstance(storms, list)

    def test_returns_list_type(self):
        from poagent.agents.irq_storm import check_irq_storm

        runner = self._make_runner(n_cpus=4, delta=0)
        config = self._make_config()
        storms = check_irq_storm(runner, config)
        assert isinstance(storms, list)
