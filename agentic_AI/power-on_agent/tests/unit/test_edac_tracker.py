"""Tests for edac_tracker.py.

Critical constraints under test:
- [CG-06] DRAM_MARGINAL if ce_rate > 100 correctable errors/minute
- DRAM_UNCORRECTABLE if ue_delta > 0
- compute_ecc_delta correctly computes delta between two EccSnapshots
- EccDeltaReport has dram_marginal, dram_uncorrectable flags
- read_edac_counts() returns EccSnapshot with ce/ue fields
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from poagent.agents.edac_tracker import EccSnapshot, EccDeltaReport, compute_ecc_delta


def _snap(ce: int, ue: int, source: str = "edac_mc") -> EccSnapshot:
    return EccSnapshot(ce=ce, ue=ue, source=source)


class TestComputeEccDelta:
    """Test compute_ecc_delta() behavior."""

    def test_no_errors_pass(self):
        t0 = _snap(ce=0, ue=0)
        t1 = _snap(ce=0, ue=0)
        result = compute_ecc_delta(t0, t1, window_min=10.0)
        assert isinstance(result, EccDeltaReport)
        assert result.ce_delta == 0
        assert result.dram_marginal is False
        assert result.dram_uncorrectable is False

    def test_ue_delta_triggers_uncorrectable(self):
        """Any UE increase → DRAM_UNCORRECTABLE."""
        t0 = _snap(ce=0, ue=0)
        t1 = _snap(ce=0, ue=1)
        result = compute_ecc_delta(t0, t1, window_min=10.0)
        assert result.ue_delta == 1
        assert result.dram_uncorrectable is True

    def test_ce_rate_above_100_per_min_triggers_marginal(self):
        """[CG-06] CE rate > 100/min → DRAM_MARGINAL."""
        t0 = _snap(ce=0, ue=0)
        t1 = _snap(ce=200, ue=0)  # 200 CE in 1 minute = 200/min > 100
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.ce_delta == 200
        assert result.ce_rate_per_min > 100
        assert result.dram_marginal is True

    def test_ce_rate_below_100_per_min_passes(self):
        """CE rate ≤ 100/min → not marginal."""
        t0 = _snap(ce=0, ue=0)
        t1 = _snap(ce=50, ue=0)  # 50 CE in 1 minute = 50/min ≤ 100
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.dram_marginal is False

    def test_delta_is_non_negative_on_counter_wrap(self):
        """If t1 < t0 (counter reset), delta should be 0 (max(0, ...))."""
        t0 = _snap(ce=100, ue=0)
        t1 = _snap(ce=5, ue=0)  # counter reset
        result = compute_ecc_delta(t0, t1, window_min=10.0)
        assert result.ce_delta >= 0

    def test_ue_triggers_uncorrectable_over_marginal(self):
        """Both high CE and UE → dram_uncorrectable=True."""
        t0 = _snap(ce=0, ue=0)
        t1 = _snap(ce=500, ue=2)
        result = compute_ecc_delta(t0, t1, window_min=1.0)
        assert result.dram_uncorrectable is True
        assert result.ue_delta == 2

    def test_unavailable_source_sets_not_monitorable(self):
        """EccSnapshot with source='unavailable' → ecc_not_monitorable."""
        t0 = EccSnapshot(ce=None, ue=None, source="unavailable")
        t1 = EccSnapshot(ce=None, ue=None, source="unavailable")
        result = compute_ecc_delta(t0, t1, window_min=10.0)
        assert result.ecc_not_monitorable is True


class TestEccSnapshot:
    def test_snapshot_fields(self):
        snap = EccSnapshot(ce=42, ue=0, source="edac_mc")
        assert snap.ce == 42
        assert snap.ue == 0
        assert snap.source == "edac_mc"

    def test_snapshot_default_source(self):
        snap = EccSnapshot()
        assert snap.source == "unavailable"

    def test_snapshot_with_counters(self):
        snap = EccSnapshot(ce=10, ue=0, source="edac_mc", counters={"mc0": 10})
        assert snap.counters == {"mc0": 10}


class _EdacResult:
    """Simulate runner.exec() result object."""
    def __init__(self, rc=0, stdout=""):
        self.returncode = rc
        self.stdout = stdout


class _EdacMockRunner:
    """Mock runner matching the actual read_edac_counts() API.

    read_edac_counts uses:
      - runner.path_exists(path) → bool
      - runner.glob_read(pattern) → list[str]
      - runner.glob(pattern) → list[str]
      - runner.read_file(path) → str
      - runner.exec(cmd, timeout, probe_name) → obj with .stdout/.returncode
    """

    def __init__(self, edac_present: bool = False, exec_responses: dict | None = None):
        self._edac_present = edac_present
        self._exec_responses = exec_responses or {}

    def path_exists(self, path: str) -> bool:
        if "/edac/mc/" in path:
            return self._edac_present
        return False

    def glob(self, pattern: str) -> list[str]:
        return []

    def glob_read(self, pattern: str) -> list[str]:
        return []

    def read_file(self, path: str) -> str:
        return ""

    def exec(self, cmd: str, timeout=None, probe_name="") -> _EdacResult:
        for pattern, (rc, out) in self._exec_responses.items():
            if pattern in cmd:
                return _EdacResult(rc, out)
        return _EdacResult(1, "")  # default: error


class TestReadEdacCounts:
    """Test read_edac_counts() with mocked runner."""

    def test_no_edac_sysfs_returns_unavailable_snapshot(self):
        from poagent.agents.edac_tracker import read_edac_counts

        runner = _EdacMockRunner(edac_present=False)
        result = read_edac_counts(runner)
        assert result is not None
        assert isinstance(result, EccSnapshot)
        assert result.source == "unavailable"

    def test_ecc_not_monitorable_when_all_sources_fail(self):
        """No EDAC source found → ECC_NOT_MONITORABLE note."""
        from poagent.agents.edac_tracker import read_edac_counts

        runner = _EdacMockRunner(edac_present=False)
        result = read_edac_counts(runner)
        assert result is not None
        assert "MONITORABLE" in result.note.upper() or result.source == "unavailable"

    def test_dmesg_fallback_used_when_keyword_found(self):
        """If dmesg has ECC keywords, source='dmesg_keyword'."""
        from poagent.agents.edac_tracker import read_edac_counts

        runner = _EdacMockRunner(
            edac_present=False,
            exec_responses={"dmesg": (0, "ecc correctable error detected")},
        )
        result = read_edac_counts(runner)
        assert result is not None
        assert result.source == "dmesg_keyword"
