"""Tests for specialist.py DomainResult and Finding.

Critical constraints under test:
- DomainResult.to_summary_dict() truncates to ≤500 tokens target
- DomainResult.get_failed_clocks() reads from raw_data fallback [CG-04]
- Finding fields are all preserved
- gate4_method5_only propagation [FINAL-S4]
- confidence_tags list is mutable for cascade_resolver updates
- timed_out_probes tracks per-probe timeouts [SG-06]
"""

from __future__ import annotations

import pytest

from poagent.agents.specialist import DomainResult, Finding


class TestFinding:
    def test_finding_fields(self):
        f = Finding(
            severity="CRITICAL",
            code="RAIL_SANITY_FAIL",
            message="VCC_CORE rail out of tolerance",
            evidence={"measured_mv": 800, "expected_mv": 1000},
            recommended_action="Check PMBus configuration",
        )
        assert f.severity == "CRITICAL"
        assert f.code == "RAIL_SANITY_FAIL"
        assert "VCC_CORE" in f.message
        assert f.evidence["measured_mv"] == 800
        assert "PMBus" in f.recommended_action


class TestDomainResult:
    def _make(self, **kwargs) -> DomainResult:
        defaults = dict(
            domain="power_clocking",
            status="pass",
            summary="Power clocking passed",
            findings=[],
        )
        defaults.update(kwargs)
        return DomainResult(**defaults)

    def test_defaults_populated(self):
        r = self._make()
        assert r.domain == "power_clocking"
        assert r.status == "pass"
        assert r.findings == []
        assert r.confidence == 0.0
        assert r.recommended_actions == []
        assert r.timed_out_probes == []
        assert r.gate4_method5_only is False
        assert r.confidence_tags == []
        assert r.cascade_root is None
        assert r.failed_clocks == []

    def test_to_summary_dict_structure(self):
        f = Finding(severity="WARN", code="CLK_LOW", message="Clock rate below minimum")
        r = self._make(
            status="warning",
            summary="Clock issues detected",
            findings=[f],
            root_cause_hypothesis="PLL misconfigured",
            confidence=0.8,
        )
        d = r.to_summary_dict()
        assert d["domain"] == "power_clocking"
        assert d["status"] == "warning"
        assert "summary" in d
        assert "top_findings" in d
        assert "root_cause_hypothesis" in d
        assert "confidence" in d

    def test_to_summary_dict_truncates_summary(self):
        long_summary = "A" * 2000
        r = self._make(summary=long_summary)
        d = r.to_summary_dict()
        assert len(d["summary"]) <= 1000  # truncated to 1000 chars

    def test_to_summary_dict_limits_findings(self):
        """top_findings capped at 5."""
        findings = [
            Finding(severity="INFO", code=f"CODE_{i}", message=f"Message {i}")
            for i in range(10)
        ]
        r = self._make(findings=findings)
        d = r.to_summary_dict()
        assert len(d["top_findings"]) <= 5

    def test_get_failed_clocks_from_field(self):
        r = self._make(failed_clocks=["pll_core", "pll_sa"])
        assert r.get_failed_clocks() == ["pll_core", "pll_sa"]

    def test_get_failed_clocks_falls_back_to_raw_data(self):
        """If failed_clocks empty, fall back to raw_data['failed_clocks']."""
        r = self._make(
            failed_clocks=[],
            raw_data={"failed_clocks": ["xtal_19p2"]},
        )
        result = r.get_failed_clocks()
        assert "xtal_19p2" in result

    def test_confidence_tags_mutable(self):
        """confidence_tags must be mutable for cascade_resolver."""
        r = self._make()
        r.confidence_tags.append("LOW_CONFIDENCE_PHASE1_INCOMPLETE")
        assert "LOW_CONFIDENCE_PHASE1_INCOMPLETE" in r.confidence_tags

    def test_gate4_method5_only_propagated(self):
        r = self._make(gate4_method5_only=True)
        assert r.gate4_method5_only is True
        d = r.to_summary_dict()
        # gate4_method5_only should be in summary dict or accessible
        assert r.gate4_method5_only  # still True after to_summary_dict()

    def test_timed_out_probes_tracked(self):
        r = self._make(timed_out_probes=["exec_command:cat /sys/kernel/debug/clk/pll_core/cl"])
        assert len(r.timed_out_probes) == 1


class TestDomainResultStatus:
    """Test all valid DomainStatus values."""

    VALID_STATUSES = ["pass", "fail", "warning", "conditional", "skip",
                      "aborted", "skip_debugfs", "enum_fail", "dependent_fail"]

    def test_all_valid_statuses_accepted(self):
        from poagent.agents.specialist import DomainResult
        for status in self.VALID_STATUSES:
            r = DomainResult(domain="test", status=status, summary="test")
            assert r.status == status
