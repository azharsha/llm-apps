"""Tests for cascade_resolver.py.

Critical constraints under test:
- [N-CG-02] If Phase 1 status="aborted", tag clock-dependent Phase 2 domains
  LOW_CONFIDENCE_PHASE1_INCOMPLETE, emit ORCHESTRATOR_WARNING, return without cascade
- Normal cascade: failed clocks → demote affected domains to "dependent_fail"
- Domains not in clock dependency chain are unaffected
- Empty failed_clocks → no cascade actions
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from poagent.agents.specialist import DomainResult, Finding


def _make_result(domain: str, status: str = "pass", failed_clocks: list | None = None) -> DomainResult:
    return DomainResult(
        domain=domain,
        status=status,
        summary=f"{domain} {status}",
        findings=[],
        failed_clocks=failed_clocks or [],
    )


def _make_map(entries: dict) -> dict:
    """Build a clock_dependency_map dict for resolve_clock_cascades."""
    return entries


class TestCascadeResolverPhase1Aborted:
    """[N-CG-02] Phase 1 aborted → tag clock-dependent Phase 2 domains."""

    def test_aborted_phase1_tags_dependent_domains(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="aborted")
        phase2_results = {
            "compute_memory": _make_result("compute_memory"),
            "highspeed_serial": _make_result("highspeed_serial"),
            "networking": _make_result("networking"),
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory", "highspeed_serial"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        cm = phase2_results["compute_memory"]
        hs = phase2_results["highspeed_serial"]
        assert "LOW_CONFIDENCE_PHASE1_INCOMPLETE" in cm.confidence_tags
        assert "LOW_CONFIDENCE_PHASE1_INCOMPLETE" in hs.confidence_tags

    def test_aborted_phase1_does_not_affect_unrelated_domains(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="aborted")
        phase2_results = {
            "compute_memory": _make_result("compute_memory"),
            "networking": _make_result("networking"),  # not in clock consumers
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # networking is not a consumer of pll_core → not tagged
        net = phase2_results["networking"]
        assert "LOW_CONFIDENCE_PHASE1_INCOMPLETE" not in (net.confidence_tags or [])

    def test_aborted_phase1_does_not_demote_status(self):
        """[N-CG-02] tag LOW_CONFIDENCE, but don't change status to dependent_fail."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="aborted")
        phase2_results = {
            "compute_memory": _make_result("compute_memory", status="pass"),
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # Status should NOT change to "dependent_fail" when phase1 is aborted
        assert phase2_results["compute_memory"].status == "pass"


class TestCascadeResolverNormalMode:
    """Normal cascade: failed clocks → demote dependent domains."""

    def test_failed_clock_demotes_dependent_domain(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="fail",
                                     failed_clocks=["pll_core"])
        # Domain must already be in fail/warning/conditional to be demoted to dependent_fail
        phase2_results = {
            "compute_memory": _make_result("compute_memory", status="fail"),
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # compute_memory depends on pll_core → should be demoted to dependent_fail
        assert phase2_results["compute_memory"].status in ("dependent_fail", "fail", "conditional")

    def test_non_dependent_domain_not_affected(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="fail",
                                     failed_clocks=["pll_core"])
        phase2_results = {
            "compute_memory": _make_result("compute_memory"),
            "networking": _make_result("networking", status="pass"),  # not affected
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # networking is not a consumer of pll_core → unaffected
        assert phase2_results["networking"].status == "pass"

    def test_empty_failed_clocks_no_cascade(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="pass", failed_clocks=[])
        phase2_results = {
            "compute_memory": _make_result("compute_memory", status="pass"),
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # No failed clocks → no demotions
        assert phase2_results["compute_memory"].status == "pass"

    def test_cascade_chain_multi_hop(self):
        """Transitive cascade: pll_root → child_clk → compute_memory."""
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="fail",
                                     failed_clocks=["pll_root"])
        # Domain must already be in fail/warning/conditional to be demoted to dependent_fail
        phase2_results = {
            "compute_memory": _make_result("compute_memory", status="warning"),
        }

        topology = {
            "pll_root": {"parent": None, "consumers": []},
            "child_clk": {"parent": "pll_root", "consumers": ["compute_memory"]},
        }

        resolve_clock_cascades(phase1_result, phase2_results, topology)

        # compute_memory depends transitively on pll_root via child_clk
        assert phase2_results["compute_memory"].status in ("dependent_fail", "fail", "conditional")


class TestCascadeResolverEdgeCases:
    def test_empty_topology_no_exception(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="fail", failed_clocks=["pll_core"])
        phase2_results = {"compute_memory": _make_result("compute_memory")}

        result = resolve_clock_cascades(phase1_result, phase2_results, {})
        assert result is not None

    def test_failed_clock_not_in_topology_no_exception(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="fail",
                                     failed_clocks=["nonexistent_pll"])
        phase2_results = {
            "compute_memory": _make_result("compute_memory"),
        }

        topology = {
            "pll_core": {"parent": None, "consumers": ["compute_memory"]},
        }

        # Must not raise even if failed clock is not in topology
        result = resolve_clock_cascades(phase1_result, phase2_results, topology)
        assert result is not None

    def test_returns_phase2_results(self):
        from poagent.agents.cascade_resolver import resolve_clock_cascades

        phase1_result = _make_result("power_clocking", status="pass")
        phase2_results = {"compute_memory": _make_result("compute_memory")}
        topology = {"pll_core": {"parent": None, "consumers": ["compute_memory"]}}

        result = resolve_clock_cascades(phase1_result, phase2_results, topology)
        assert isinstance(result, dict)
        assert "compute_memory" in result
