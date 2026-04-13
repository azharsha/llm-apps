"""Tests for triage.py — compute_po_verdict() and related.

Critical constraints under test:
- [FINAL-H3] po_verdict is Python-computed, NEVER by LLM
- [LAST-S4] silicon_stepping.source=="fallback" → po_verdict >= CONDITIONAL
- Verdict order: PASS < CONDITIONAL < FAIL
- Domain status "fail" → FAIL verdict
- Domain status "conditional" → CONDITIONAL
- Domain status "pass" → PASS (if no other issues)
- Empty results → INCOMPLETE verdict
"""

from __future__ import annotations

import pytest

from poagent.agents.specialist import DomainResult, Finding
from poagent.agents.triage import compute_po_verdict


def _make_result(domain: str, status: str, confidence: float = 0.9) -> DomainResult:
    return DomainResult(
        domain=domain,
        status=status,
        summary=f"{domain}: {status}",
        confidence=confidence,
        findings=[],
    )


def _bc(source: str = "platform", panics: list | None = None) -> dict:
    """Build a minimal boot_context dict."""
    return {
        "silicon_stepping": {"source": source, "platform": "TGL", "raw": "B1"},
        "kernel_panics_this_boot": panics or [],
    }


class TestComputePoVerdict:
    """[FINAL-H3] Python-computed verdict tests."""

    def test_all_pass_returns_pass(self):
        results = {
            "power_clocking": _make_result("power_clocking", "pass"),
            "compute_memory": _make_result("compute_memory", "pass"),
        }
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "PASS"

    def test_any_fail_returns_fail(self):
        results = {
            "power_clocking": _make_result("power_clocking", "pass"),
            "compute_memory": _make_result("compute_memory", "fail"),
        }
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "FAIL"

    def test_warning_maps_to_pass(self):
        """warning status maps to PASS per _VERDICT_FROM_STATUS."""
        results = {
            "power_clocking": _make_result("power_clocking", "pass"),
            "compute_memory": _make_result("compute_memory", "warning"),
        }
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "PASS"

    def test_conditional_result_returns_conditional(self):
        results = {"power_clocking": _make_result("power_clocking", "conditional")}
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "CONDITIONAL"

    def test_aborted_returns_conditional(self):
        """aborted status maps to CONDITIONAL per _VERDICT_FROM_STATUS."""
        results = {
            "power_clocking": _make_result("power_clocking", "aborted"),
            "compute_memory": _make_result("compute_memory", "aborted"),
        }
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "CONDITIONAL"

    def test_fail_overrides_conditional(self):
        """FAIL must not be downgraded to CONDITIONAL."""
        results = {
            "power_clocking": _make_result("power_clocking", "fail"),
            "compute_memory": _make_result("compute_memory", "conditional"),
        }
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert verdict == "FAIL"

    def test_empty_results_returns_incomplete(self):
        verdict, reason = compute_po_verdict(domain_results={}, boot_context=_bc())
        assert verdict == "INCOMPLETE"

    def test_reason_is_string(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(domain_results=results, boot_context=_bc())
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_preflight_aborted_returns_incomplete(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(), preflight_aborted=True
        )
        assert verdict == "INCOMPLETE"

    def test_barrier_failed_returns_fail(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(), barrier_failed=True
        )
        assert verdict == "FAIL"


class TestSiliconSteppingFallback:
    """[LAST-S4] fallback source → CONDITIONAL minimum."""

    def test_fallback_stepping_upgrades_pass_to_conditional(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(source="fallback")
        )
        # PASS → CONDITIONAL due to LAST-S4
        assert verdict in ("CONDITIONAL", "FAIL")
        assert "SILICON_STEPPING_UNRESOLVED" in reason

    def test_fallback_stepping_does_not_downgrade_fail(self):
        """LAST-S4: max() preserves FAIL — fallback never downgrades FAIL."""
        results = {"power_clocking": _make_result("power_clocking", "fail")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(source="fallback")
        )
        assert verdict == "FAIL"

    def test_platform_stepping_no_forced_conditional(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(source="platform")
        )
        assert verdict == "PASS"

    def test_non_fallback_source_no_forced_conditional(self):
        """cpuid/dmi source is not 'fallback' so no forced CONDITIONAL."""
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(source="cpuid")
        )
        assert verdict == "PASS"


class TestKernelPanicEffect:
    """Kernel panics → upgrade verdict to CONDITIONAL minimum."""

    def test_panic_detected_upgrades_to_conditional(self):
        """panic pattern in boot_context → minimum CONDITIONAL."""
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        panics = [{"pattern": "panic", "message": "kernel panic"}]
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(panics=panics)
        )
        assert verdict in ("CONDITIONAL", "FAIL")

    def test_no_panic_no_forced_conditional(self):
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(panics=[])
        )
        assert verdict == "PASS"

    def test_non_matching_panic_pattern_no_upgrade(self):
        """Only panic/bug/gpf patterns trigger CONDITIONAL upgrade."""
        results = {"power_clocking": _make_result("power_clocking", "pass")}
        panics = [{"pattern": "oops_other", "message": "some warning"}]
        verdict, reason = compute_po_verdict(
            domain_results=results, boot_context=_bc(panics=panics)
        )
        assert verdict == "PASS"


class TestVerdictOrdering:
    """Validate verdict ordering invariants."""

    def test_fail_beats_conditional(self):
        from poagent.agents.triage import _verdict_max
        assert _verdict_max("FAIL", "CONDITIONAL") == "FAIL"

    def test_conditional_beats_pass(self):
        from poagent.agents.triage import _verdict_max
        assert _verdict_max("CONDITIONAL", "PASS") == "CONDITIONAL"

    def test_fail_beats_pass(self):
        from poagent.agents.triage import _verdict_max
        assert _verdict_max("FAIL", "PASS") == "FAIL"

    def test_same_verdict_returns_same(self):
        from poagent.agents.triage import _verdict_max
        assert _verdict_max("PASS", "PASS") == "PASS"
        assert _verdict_max("FAIL", "FAIL") == "FAIL"

    def test_incomplete_handling(self):
        from poagent.agents.triage import _verdict_max
        # INCOMPLETE not in _VERDICT_ORDER → order 0, same as PASS
        result = _verdict_max("INCOMPLETE", "PASS")
        assert isinstance(result, str)
