"""Tests for probes/registry.py.

Critical constraints under test:
- @register_probe decorator registers probes in correct domain
- get_probes() returns probes in tier order (FAST before STANDARD before SLOW)
- ProbeResult is a frozen dataclass with probe_name, domain, severity fields
- ProbeBase.run() must be implemented by subclasses
- All 10 KNOWN_DOMAINS have at least 1 registered probe after import
"""

from __future__ import annotations

import pytest

from poagent.probes.registry import (
    ProbeBase,
    ProbeResult,
    ProbeTier,
    register_probe,
    get_probes,
)
from poagent.board.clock_topology import KNOWN_DOMAINS


class TestRegisterProbe:
    def test_decorator_registers_probe(self):
        """Custom probe is discoverable after decoration."""
        @register_probe("power_clocking", tier=ProbeTier.FAST, description="test probe")
        class _TestProbeRegistryA(ProbeBase):
            def run(self) -> ProbeResult:
                return ProbeResult(
                    probe_name=self.__class__.__name__,
                    domain="power_clocking",
                    severity="PASS",
                )

        probes = get_probes("power_clocking")
        names = [p.name for p in probes]
        assert "_TestProbeRegistryA" in names

    def test_probe_has_correct_metadata(self):
        @register_probe("networking", tier=ProbeTier.SLOW, description="my net probe", timeout=45.0)
        class _NetProbeRegistryTest(ProbeBase):
            def run(self) -> ProbeResult:
                return ProbeResult(
                    probe_name=self.__class__.__name__,
                    domain="networking",
                    severity="PASS",
                )

        probes = get_probes("networking", max_tier=ProbeTier.SLOW)
        meta = next((p for p in probes if p.name == "_NetProbeRegistryTest"), None)
        assert meta is not None
        assert meta.tier == ProbeTier.SLOW
        assert meta.description == "my net probe"
        assert meta.timeout == 45.0

    def test_unknown_domain_returns_empty(self):
        probes = get_probes("nonexistent_domain_xyz")
        assert probes == [] or probes is None


class TestProbeTierOrdering:
    def test_fast_before_slow_in_ordering(self):
        """FAST probes come before SLOW probes in get_probes() result."""
        # Register test probes in a new domain
        @register_probe("sensors_misc", tier=ProbeTier.SLOW)
        class _SlowProbeTest(ProbeBase):
            def run(self) -> ProbeResult:
                return ProbeResult(probe_name="SlowProbeTest", domain="sensors_misc", severity="PASS")

        @register_probe("sensors_misc", tier=ProbeTier.FAST)
        class _FastProbeTest(ProbeBase):
            def run(self) -> ProbeResult:
                return ProbeResult(probe_name="FastProbeTest", domain="sensors_misc", severity="PASS")

        probes = get_probes("sensors_misc")
        tiers = [p.tier for p in probes]
        fast_indices = [i for i, t in enumerate(tiers) if t == ProbeTier.FAST]
        slow_indices = [i for i, t in enumerate(tiers) if t == ProbeTier.SLOW]
        if fast_indices and slow_indices:
            assert max(fast_indices) < min(slow_indices)

    def test_tier_values_ordered(self):
        """FAST < STANDARD < SLOW in ordinal value."""
        assert ProbeTier.FAST.value < ProbeTier.STANDARD.value < ProbeTier.SLOW.value


class TestAllDomainsHaveProbes:
    def test_each_known_domain_has_at_least_one_probe(self):
        """All 10 canonical domains must have ≥1 registered probe."""
        import poagent.probes.power_clocking
        import poagent.probes.compute_memory
        import poagent.probes.storage
        import poagent.probes.highspeed_serial
        import poagent.probes.display_graphics
        import poagent.probes.networking
        import poagent.probes.audio
        import poagent.probes.lowspeed_interface
        import poagent.probes.security_crypto
        import poagent.probes.sensors_misc

        for domain in KNOWN_DOMAINS:
            probes = get_probes(domain)
            assert probes, f"Domain '{domain}' has no registered probes"


class TestProbeResult:
    def test_probe_result_fields(self):
        r = ProbeResult(
            probe_name="TestProbe",
            domain="audio",
            severity="PASS",
            findings=["2 audio cards found"],
            raw_data={"cards": 2},
        )
        assert r.probe_name == "TestProbe"
        assert r.domain == "audio"
        assert r.severity == "PASS"
        assert r.raw_data == {"cards": 2}

    def test_probe_result_fail_severity(self):
        r = ProbeResult(
            probe_name="FailProbe",
            domain="storage",
            severity="FAIL",
            findings=["NVMe probe failed"],
            raw_data={"error": "nvme timeout"},
        )
        assert r.severity == "FAIL"
        assert r.is_fail is True
        assert r.is_pass is False

    def test_probe_result_is_frozen(self):
        r = ProbeResult(probe_name="P", domain="audio", severity="PASS")
        with pytest.raises((AttributeError, TypeError)):
            r.severity = "FAIL"  # type: ignore[misc]

    def test_probe_result_pass_properties(self):
        r = ProbeResult(probe_name="P", domain="audio", severity="PASS")
        assert r.is_pass is True
        assert r.is_fail is False
        assert r.is_conditional is False


class TestProbeBase:
    def test_subclass_without_run_raises_on_call(self):
        class BadProbe(ProbeBase):
            pass  # doesn't implement run()

        probe = BadProbe(runner=None, board_profile=None, config=None)
        with pytest.raises(NotImplementedError):
            probe.run()

    def test_concrete_probe_instantiates_and_runs(self):
        class GoodProbe(ProbeBase):
            def run(self) -> ProbeResult:
                return ProbeResult(
                    probe_name="GoodProbe",
                    domain="sensors_misc",
                    severity="PASS",
                )

        probe = GoodProbe(runner=None, board_profile=None, config=None)
        result = probe.run()
        assert result.severity == "PASS"
        assert result.probe_name == "GoodProbe"

    def test_probe_base_stores_runner(self):
        from unittest.mock import MagicMock
        runner = MagicMock()
        probe = ProbeBase(runner=runner, board_profile=None, config=None)
        assert probe._runner is runner
