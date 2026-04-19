"""
test_cascade.py — Phase 4 v4.0.0
35 tests for CascadeEdge, CascadeResult, and analyse().
Expected: 35 PASSED, 0 FAILED
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.cascade import (
    CascadeEdge, CascadeResult, analyse,
    _break_cycles, _has_cycle, _get_provider_rules,
)
from soctriage.core.soc_provider import SoCProvider
from soctriage.core.tokenizer import LogToken

# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(
    line_no: int,
    token_type: str = "unknown",
    arch: str = "unknown",
    chip_gen: str = "unknown",
    kernel_ver: str | None = None,
) -> LogToken:
    return LogToken(
        line_no=line_no,
        raw="test",
        token_type=token_type,
        arch=arch,
        chip_gen=chip_gen,
        kernel_ver=kernel_ver,
        timestamp=None,
        is_duplicate=False,
        confidence=1.0,
    )


def _make_event(
    event_id: int,
    event_type: str,
    severity: str,
    subsystem: str = "unknown",
    start_line: int = 1,
    end_line: int = 1,
    chip_gen: str = "unknown",
    arch: str = "unknown",
    kernel_ver: str | None = None,
    confidence: float = 0.7,
    raw_text: str = "test line",
) -> LogEvent:
    """Build a LogEvent directly for cascade tests (bypasses assembler pipeline)."""
    tok = _tok(start_line, arch=arch, chip_gen=chip_gen, kernel_ver=kernel_ver)
    return LogEvent(
        event_id=event_id,
        event_type=event_type,
        severity=severity,
        subsystem=subsystem,
        ip_block="unknown",
        tokens=[tok],
        start_line=start_line,
        end_line=end_line,
        arch=arch,
        chip_gen=chip_gen,
        kernel_ver=kernel_ver,
        confidence=confidence,
        raw_text=raw_text,
        has_call_trace=False,
        has_registers=False,
        provider_name="generic",
    )


class _StubProvider(SoCProvider):
    """Minimal provider — raises NotImplementedError for Phase 5 methods."""

    def __init__(self, name: str = "generic") -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def detect(self, raw_log: str) -> float:
        raise NotImplementedError

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def resolve_cascade(self, ip_hits: list[dict[str, Any]]) -> list[str]:
        raise NotImplementedError

    def get_playbook(self, ip_block: str) -> dict[str, Any]:
        raise NotImplementedError

    def decode_registers(self, raw_registers: dict[str, int]) -> dict[str, Any]:
        raise NotImplementedError

    def get_register_maps(self) -> dict[str, dict[int, str]]:
        raise NotImplementedError

    def get_hang_rules(self):  # type: ignore[override]
        raise NotImplementedError


# ── CascadeResult + CascadeEdge dataclass ─────────────────────────────────────


def test_cascade_result_importable():
    from soctriage.core.cascade import CascadeResult, CascadeEdge  # noqa: F401


def test_cascade_edge_fields():
    edge = CascadeEdge(
        source_id=1, target_id=2,
        relation="causes", confidence=0.85,
        reasoning="test reason",
    )
    assert edge.source_id == 1
    assert edge.target_id == 2
    assert edge.relation == "causes"
    assert edge.confidence == 0.85
    assert edge.reasoning == "test reason"


def test_cascade_result_to_dict_is_json_serialisable():
    ev = _make_event(1, "firmware_fail", "error", "firmware", 1, 10, "intel_dg2", "x86_64", "6.8.0")
    result = analyse([ev])
    d = result.to_dict()
    # Must not raise
    serialised = json.dumps(d)
    assert isinstance(serialised, str)
    assert len(serialised) > 0


# ── analyse() basic contract ───────────────────────────────────────────────────


def test_analyse_returns_cascade_result():
    ev = _make_event(1, "gpu_hang", "critical", "gpu")
    result = analyse([ev])
    assert isinstance(result, CascadeResult)


def test_ec21_empty_event_list():
    result = analyse([])
    assert result.event_count == 0
    assert result.edges == []
    assert result.root_cause_id is None
    assert result.root_cause_conf == 0.0


def test_ec22_single_event_is_root_cause():
    ev = _make_event(1, "gpu_hang", "critical", "gpu")
    result = analyse([ev])
    assert result.root_cause_id == ev.event_id
    assert result.event_count == 1
    assert result.edges == []


def test_analyse_sets_severity_to_highest():
    e1 = _make_event(1, "warning_event", "warning", "cpu", start_line=1)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu", start_line=10)
    e3 = _make_event(3, "firmware_fail", "error",    "firmware", start_line=5)
    result = analyse([e1, e2, e3])
    assert result.severity == "critical"


# ── Causal edge building ───────────────────────────────────────────────────────


def test_cr01_smmu_causes_gpu_hang():
    e1 = _make_event(1, "smmu_fault", "error",    "interconnect", start_line=1)
    e2 = _make_event(2, "gpu_hang",   "critical", "gpu",          start_line=20)
    result = analyse([e1, e2])
    causes = [e for e in result.edges if e.relation == "causes"
              and e.source_id == 1 and e.target_id == 2]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.85)


def test_cr05_gpu_hang_causes_kernel_panic():
    e1 = _make_event(1, "gpu_hang",      "critical", "gpu", start_line=1)
    e2 = _make_event(2, "kernel_panic",  "critical", "cpu", start_line=30)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.75)


def test_cr07_firmware_fail_causes_gpu_hang():
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=20)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.90)


def test_cr12_lockup_causes_kernel_panic():
    e1 = _make_event(1, "lockup",       "critical", "cpu", start_line=1)
    e2 = _make_event(2, "kernel_panic", "critical", "cpu", start_line=15)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.95)


def test_cr17_soc_crash_causes_panic():
    e1 = _make_event(1, "soc_crash",    "critical", "remoteproc", start_line=1)
    e2 = _make_event(2, "kernel_panic", "critical", "cpu",        start_line=20)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.90)


def test_cr25_gpu_hang_causes_gpu_reset():
    e1 = _make_event(1, "gpu_hang",  "critical", "gpu", start_line=1)
    e2 = _make_event(2, "gpu_reset", "error",    "gpu", start_line=10)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.95)


def test_cr27_mce_causes_memory_fault():
    e1 = _make_event(1, "mce_error",    "error",    "soc_platform", start_line=1)
    e2 = _make_event(2, "memory_fault", "critical", "memory",       start_line=15)
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.85)


def test_warning_precedes_with_low_confidence():
    e1 = _make_event(1, "warning_event", "warning",  "cpu", start_line=1)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu", start_line=20)
    result = analyse([e1, e2])
    edges = [e for e in result.edges if e.source_id == 1 and e.target_id == 2]
    assert len(edges) == 1
    assert edges[0].relation == "precedes"
    assert edges[0].confidence == pytest.approx(0.20)


# ── Root cause algorithm ───────────────────────────────────────────────────────


def test_root_cause_is_earliest_high_outdegree_event():
    # firmware_fail causes both gpu_hang and kernel_panic → highest out-degree
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=20)
    e3 = _make_event(3, "kernel_panic",  "critical", "cpu",      start_line=50)
    result = analyse([e1, e2, e3])
    assert result.root_cause_id == 1


def test_root_cause_not_assigned_to_info_event():
    e1 = _make_event(1, "info_event",  "info",     "unknown", start_line=1)
    e2 = _make_event(2, "gpu_hang",    "critical", "gpu",     start_line=20)
    result = analyse([e1, e2])
    assert result.root_cause_id == e2.event_id


def test_root_cause_confidence_scales_with_outdegree():
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1,  confidence=0.8)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=10, confidence=0.7)
    e3 = _make_event(3, "kernel_panic",  "critical", "cpu",      start_line=30, confidence=0.9)
    result = analyse([e1, e2, e3])
    # firmware_fail has 2 causes edges (→gpu_hang, →kernel_panic), so out_degree=2
    # conf = min(1.0, 0.4 + 0.1*2 + 0.8*0.3) = min(1.0, 0.4 + 0.2 + 0.24) = 0.84
    assert result.root_cause_conf == pytest.approx(0.84, abs=0.01)


def test_root_cause_tiebreaker_earliest_line():
    # Two firmware_fail events — same event_type, different start lines
    # Both are error severity, neither is caused by something else
    # Earlier one (start_line=1) should win tiebreaker
    e1 = _make_event(1, "firmware_fail", "error", "firmware", start_line=1,  confidence=0.7)
    e2 = _make_event(2, "firmware_fail", "error", "firmware", start_line=50, confidence=0.7)
    e3 = _make_event(3, "kernel_panic",  "critical", "cpu",   start_line=80, confidence=0.9)
    result = analyse([e1, e2, e3])
    # Both firmware_fail events appear earliest; e1 has start_line=1 vs e2=50
    assert result.root_cause_id == e1.event_id


def test_ec24_all_info_events_root_cause_fallback():
    # No events with severity >= error → fallback to all events as candidates
    e1 = _make_event(1, "info_event", "info", "unknown", start_line=1,  confidence=0.5)
    e2 = _make_event(2, "info_event", "info", "unknown", start_line=10, confidence=0.4)
    result = analyse([e1, e2])
    # Root cause assigned to earliest (no causes edges)
    assert result.root_cause_id == e1.event_id
    # Confidence: conf = min(1.0, 0.4 + 0.1*0 + 0.5*0.3) = 0.55
    assert result.root_cause_conf == pytest.approx(0.55, abs=0.01)


# ── Provider-specific rules ────────────────────────────────────────────────────


def test_intel_ci01_guc_firmware_fail_confidence():
    """Intel provider: firmware_fail → gpu_hang uses CI-01 (conf=0.95) not CR-07 (0.90)."""
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1,  chip_gen="intel_dg2")
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=20, chip_gen="intel_dg2")
    result = analyse([e1, e2], use_provider_rules=True)
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.95)


def test_amd_ca01_psp_fail_causes_panic():
    """AMD provider: firmware_fail → kernel_panic uses CA-01 (conf=0.95) not CR-08 (0.85)."""
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1,  chip_gen="amd_rdna3")
    e2 = _make_event(2, "kernel_panic",  "critical", "cpu",      start_line=30, chip_gen="amd_rdna3")
    result = analyse([e1, e2], use_provider_rules=True)
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.95)


def test_qcom_cq01_adsp_crash_causes_panic():
    """Qualcomm provider: soc_crash → kernel_panic uses CQ-01 (conf=0.90)."""
    e1 = _make_event(1, "soc_crash",    "critical", "remoteproc", start_line=1,  chip_gen="qcom_sm8650")
    e2 = _make_event(2, "kernel_panic", "critical", "cpu",        start_line=20, chip_gen="qcom_sm8650")
    result = analyse([e1, e2], use_provider_rules=True)
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.90)


def test_ec26_no_provider_uses_core_rules_only():
    """Without a provider, chip_gen="intel_dg2" must NOT get Intel-specific rules."""
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1,  chip_gen="intel_dg2")
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=20, chip_gen="intel_dg2")
    # No provider rules → core rules only → CR-07 confidence=0.90, NOT CI-01=0.95
    result = analyse([e1, e2])
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.90)


# ── Edge cases ─────────────────────────────────────────────────────────────────


def test_ec23_cycle_detected_and_broken():
    """_break_cycles removes the lowest-confidence edge to resolve a manually crafted cycle A→B→A."""
    # Craft a cycle: E1→E2 (high conf) and E2→E1 (low conf)
    edge_fwd = CascadeEdge(source_id=1, target_id=2, relation="causes",
                           confidence=0.80, reasoning="gpu hang → panic")
    edge_rev = CascadeEdge(source_id=2, target_id=1, relation="causes",
                           confidence=0.50, reasoning="artificial reverse (lower confidence)")

    # Verify the cycle is detected before breaking
    adj: dict[int, list[int]] = {1: [2], 2: [1]}
    assert _has_cycle(adj, [1, 2]), "_has_cycle must detect the A→B→A cycle"

    # Break the cycle — lowest-confidence edge (edge_rev, 0.50) must be removed
    broken = _break_cycles([edge_fwd, edge_rev], [1, 2])

    assert len(broken) == 1, "One edge must remain after breaking the cycle"
    assert broken[0].source_id == 1 and broken[0].target_id == 2, \
        "The lower-confidence reverse edge must be the one removed"


def test_ec25_max_edges_enforced():
    """analyse() must not produce more than max_edges edges."""
    # Create many events that all trigger warning_event → any wildcard rule
    events = [_make_event(1, "warning_event", "warning", "cpu", start_line=1)]
    for i in range(2, 22):
        events.append(_make_event(i, "gpu_hang", "critical", "gpu", start_line=i * 10))
    result = analyse(events, max_edges=5)
    assert len(result.edges) <= 5


def test_ec27_performance_10k_events():
    """analyse() must complete in < 500ms for 10,000 events."""
    events = []
    for i in range(1, 10001):
        events.append(_make_event(i, "info_event", "info", "unknown", start_line=i))
    t0 = time.perf_counter()
    result = analyse(events)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"analyse() took {elapsed:.3f}s > 500ms"
    assert result.event_count > 0


def test_min_confidence_filters_low_edges():
    """Edges below min_confidence must not appear in result."""
    e1 = _make_event(1, "security_event", "warning", "security", start_line=1)
    e2 = _make_event(2, "kernel_panic",   "critical", "cpu",     start_line=20)
    # CR-29: security_event → kernel_panic, confidence=0.35
    # With min_confidence=0.40, this edge must be filtered out
    result = analyse([e1, e2], min_confidence=0.40)
    filtered = [e for e in result.edges if e.source_id == 1 and e.target_id == 2]
    assert len(filtered) == 0


def test_subsystems_hit_ordered_by_first_occurrence():
    e1 = _make_event(1, "firmware_fail", "error",    "firmware",    start_line=1)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",         start_line=10)
    e3 = _make_event(3, "kernel_panic",  "critical", "cpu",         start_line=30)
    result = analyse([e1, e2, e3])
    assert result.subsystems_hit[0] == "firmware"
    assert result.subsystems_hit[1] == "gpu"
    assert result.subsystems_hit[2] == "cpu"


# ── Fixture integration ────────────────────────────────────────────────────────
# These tests use manually constructed events matching the fixture log scenarios.
# Direct construction avoids pipeline mapping edge cases (e.g. mce_error token
# type → unknown_event in assembler) while still testing cascade logic end-to-end.


def test_firmware_gpu_panic_fixture_root_cause():
    """firmware_fail → gpu_hang → kernel_panic: root cause = firmware_fail."""
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=3,  end_line=12,
                     chip_gen="intel_dg2", arch="x86_64", kernel_ver="6.8.0-45")
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=15, end_line=67,
                     chip_gen="intel_dg2", arch="x86_64", kernel_ver="6.8.0-45")
    e3 = _make_event(3, "kernel_panic",  "critical", "cpu",      start_line=70, end_line=134,
                     chip_gen="intel_dg2", arch="x86_64", kernel_ver="6.8.0-45")
    result = analyse([e1, e2, e3])
    assert result.root_cause_id == e1.event_id
    rc_ev = next(e for e in result.events if e.event_id == result.root_cause_id)
    assert rc_ev.event_type == "firmware_fail"
    assert result.severity == "critical"


def test_smmu_gpu_panic_fixture_three_events():
    """smmu_fault → gpu_hang → kernel_panic: three events, root = smmu_fault."""
    e1 = _make_event(1, "smmu_fault",   "error",    "interconnect", start_line=3,  end_line=6)
    e2 = _make_event(2, "gpu_hang",     "critical", "gpu",          start_line=10, end_line=30)
    e3 = _make_event(3, "kernel_panic", "critical", "cpu",          start_line=35, end_line=70)
    result = analyse([e1, e2, e3])
    assert result.event_count == 3
    assert result.root_cause_id == e1.event_id
    assert result.severity == "critical"


def test_pcie_smmu_gpu_fixture_chain():
    """pcie_fault → smmu_fault → gpu_hang: chain established via CR-04, CR-01."""
    e1 = _make_event(1, "pcie_fault",  "error",    "interconnect", start_line=1,  end_line=3)
    e2 = _make_event(2, "smmu_fault",  "error",    "interconnect", start_line=10, end_line=12)
    e3 = _make_event(3, "gpu_hang",    "critical", "gpu",          start_line=20, end_line=35)
    result = analyse([e1, e2, e3])
    # CR-04: pcie_fault → smmu_fault (precedes)
    pcie_smmu = [e for e in result.edges if e.source_id == 1 and e.target_id == 2]
    assert len(pcie_smmu) == 1
    assert pcie_smmu[0].relation == "precedes"
    # CR-01: smmu_fault → gpu_hang (causes)
    smmu_gpu = [e for e in result.edges
                if e.source_id == 2 and e.target_id == 3 and e.relation == "causes"]
    assert len(smmu_gpu) == 1


def test_qcom_adsp_panic_fixture():
    """soc_crash → kernel_panic with Qualcomm provider: root = soc_crash."""
    e1 = _make_event(1, "soc_crash",    "critical", "remoteproc", start_line=5,  end_line=9,
                     chip_gen="qcom_sm8650")
    e2 = _make_event(2, "kernel_panic", "critical", "cpu",        start_line=15, end_line=25,
                     chip_gen="qcom_sm8650")
    result = analyse([e1, e2], use_provider_rules=True)
    assert result.root_cause_id == e1.event_id
    rc_ev = next(e for e in result.events if e.event_id == result.root_cause_id)
    assert rc_ev.event_type == "soc_crash"


def test_mce_memory_panic_fixture():
    """mce_error → memory_fault → kernel_panic: root = mce_error."""
    e1 = _make_event(1, "mce_error",    "error",    "soc_platform", start_line=2,  end_line=5)
    e2 = _make_event(2, "memory_fault", "critical", "memory",       start_line=8,  end_line=12)
    e3 = _make_event(3, "kernel_panic", "critical", "cpu",          start_line=15, end_line=25)
    result = analyse([e1, e2, e3])
    assert result.root_cause_id == e1.event_id
    # CR-27: mce_error → memory_fault (causes)
    mce_mem = [e for e in result.edges
               if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(mce_mem) == 1
    assert mce_mem[0].confidence == pytest.approx(0.85)


def test_power_gpu_hang_fixture_amd_provider():
    """power_fault → gpu_hang with AMD provider: CA-04 (conf=0.85) overrides CR-15 (0.75)."""
    e1 = _make_event(1, "power_fault", "error",    "power", start_line=2,  end_line=5,
                     chip_gen="amd_cdna3")
    e2 = _make_event(2, "gpu_hang",    "critical", "gpu",   start_line=10, end_line=20,
                     chip_gen="amd_cdna3")
    result = analyse([e1, e2], use_provider_rules=True)
    causes = [e for e in result.edges
              if e.source_id == 1 and e.target_id == 2 and e.relation == "causes"]
    assert len(causes) == 1
    assert causes[0].confidence == pytest.approx(0.85)
    assert result.root_cause_id == e1.event_id


# ── New tests added by phase 4 code review ────────────────────────────────────


def test_chip_gen_prefixes_match_provider_rules():
    """All tokenizer chip_gen prefixes must route to a non-empty provider rule set in cascade."""
    from soctriage.core.tokenizer import _CHIP_GEN_PREFIX_TO_PROVIDER
    for prefix in _CHIP_GEN_PREFIX_TO_PROVIDER:
        rules = _get_provider_rules(f"{prefix}_test")
        assert len(rules) > 0, f"No provider rules for chip_gen prefix '{prefix}_'"


def test_ec28_performance_10k_adversarial():
    """analyse() must complete in < 500ms for 10,000 events with many rule matches."""
    events = []
    for i in range(1, 5001):
        events.append(_make_event(i * 2 - 1, "warning_event", "warning", "cpu", start_line=i * 2 - 1))
        events.append(_make_event(i * 2,     "gpu_hang",      "critical", "gpu", start_line=i * 2))
    t0 = time.perf_counter()
    result = analyse(events, max_edges=500)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"adversarial analyse() took {elapsed:.3f}s > 500ms"
    assert result.event_count > 0


def test_e2e_firmware_gpu_panic_pipeline():
    """Full pipeline: tokenize → assemble → cascade on firmware_gpu_panic.log fixture."""
    import pathlib
    from soctriage.core.tokenizer import tokenize
    from soctriage.core.assembler import assemble

    fixture = pathlib.Path(__file__).parent / "fixtures" / "phase4" / "firmware_gpu_panic.log"
    lines = iter(fixture.read_text().splitlines())
    tokens = list(tokenize(lines))
    events = list(assemble(tokens))
    assert len(events) > 0, "Pipeline must produce at least one event from the fixture log"

    result = analyse(events)
    assert isinstance(result, CascadeResult)
    assert result.event_count > 0
    assert result.root_cause_id is not None, "Cascade must identify a root cause in this log"


def test_output_schema_keys_match_to_dict():
    """OUTPUT_SCHEMA top-level keys must exactly match CascadeResult.to_dict() keys."""
    from soctriage.core.reporter import OUTPUT_SCHEMA
    ev = _make_event(1, "firmware_fail", "error", "firmware", 1, 10, "intel_dg2", "x86_64", "6.8.0")
    result = analyse([ev])
    actual_keys = set(result.to_dict().keys())
    schema_keys = set(OUTPUT_SCHEMA.keys())
    assert actual_keys == schema_keys, (
        f"to_dict() keys {actual_keys} differ from OUTPUT_SCHEMA keys {schema_keys}"
    )
