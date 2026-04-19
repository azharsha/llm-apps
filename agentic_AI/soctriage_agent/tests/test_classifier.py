"""
test_classifier.py — Phase 3 v3.0.0
26 tests for EventClassifier and classify_all() pipeline.
Expected: 26 PASSED, 0 FAILED
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from soctriage.core.tokenizer import LogToken
from soctriage.core.assembler import LogEvent, assemble
from soctriage.core.classifier import EventClassifier, classify_all
from soctriage.core.soc_provider import SoCProvider

FIXTURES = Path("tests/fixtures/phase3")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(
    line_no: int,
    token_type: str,
    raw: str = "test line",
    arch: str = "unknown",
    chip_gen: str = "unknown",
    kernel_ver: str | None = None,
) -> LogToken:
    return LogToken(
        line_no=line_no, raw=raw, token_type=token_type,
        arch=arch, chip_gen=chip_gen, kernel_ver=kernel_ver,
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(
    token_type: str = "panic",
    line_no: int = 1,
    arch: str = "unknown",
    chip_gen: str = "unknown",
    extra_toks: list[LogToken] | None = None,
) -> LogEvent:
    """Build a minimal LogEvent for classifier tests."""
    toks = [_tok(line_no, token_type, arch=arch, chip_gen=chip_gen)]
    if extra_toks:
        toks.extend(extra_toks)
    events = list(assemble(iter(toks), skip_duplicates=False))
    return events[0]


class _StubProvider(SoCProvider):
    """Minimal provider that always raises NotImplementedError for Phase 5 stubs."""

    def name(self) -> str:
        return "StubProvider"

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


class _ReturningProvider(_StubProvider):
    """Provider whose classify_ip returns a real IP block."""

    def __init__(self, ip: str) -> None:
        self._ip = ip

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"ip": self._ip, "confidence": 0.9}]


# ── EventClassifier basic contract ────────────────────────────────────────────


def test_classifier_importable():
    from soctriage.core.classifier import EventClassifier  # noqa: F401


def test_classifier_instantiates_without_provider():
    clf = EventClassifier()
    assert clf is not None


def test_classify_returns_same_event_object():
    e = _make_event("panic")
    clf = EventClassifier()
    result = clf.classify(e)
    assert result is e


def test_classify_sets_subsystem():
    e = _make_event("panic")
    clf = EventClassifier()
    clf.classify(e)
    assert isinstance(e.subsystem, str)
    assert len(e.subsystem) > 0


# ── Subsystem routing ─────────────────────────────────────────────────────────


def test_subsystem_gpu_for_gpu_event():
    e = _make_event("gpu_event")
    EventClassifier().classify(e)
    assert e.subsystem == "gpu"


def test_subsystem_gpu_for_reset_event():
    e = _make_event("reset_event")
    EventClassifier().classify(e)
    assert e.subsystem == "gpu"


def test_subsystem_cpu_for_panic():
    e = _make_event("panic")
    EventClassifier().classify(e)
    assert e.subsystem == "cpu"


def test_subsystem_memory_for_kasan():
    """kasan_detail as first matching token → memory subsystem."""
    tok = _tok(1, "memory_event")
    kasan = _tok(2, "kasan_detail")
    events = list(assemble(iter([tok, kasan])))
    EventClassifier().classify(events[0])
    assert events[0].subsystem == "memory"


def test_subsystem_interconnect_for_pcie_error():
    e = _make_event("pcie_error")
    EventClassifier().classify(e)
    assert e.subsystem == "interconnect"


def test_subsystem_remoteproc_for_adsp_crash():
    e = _make_event("qcom_adsp_crash")
    EventClassifier().classify(e)
    assert e.subsystem == "remoteproc"


def test_subsystem_power_for_thermal_event():
    e = _make_event("thermal_event")
    EventClassifier().classify(e)
    assert e.subsystem == "power"


def test_subsystem_unknown_for_all_info_tokens():
    """Event containing only info tokens has unknown subsystem."""
    e = _make_event("info")
    EventClassifier().classify(e)
    assert e.subsystem == "unknown"


# ── IP block classification ────────────────────────────────────────────────────


def test_ip_block_unknown_when_no_provider():
    e = _make_event("panic")
    EventClassifier(provider=None).classify(e)
    assert e.ip_block == "unknown"


def test_ip_block_unknown_when_provider_not_implemented():
    """Phase 5 stub raises NotImplementedError → ip_block falls back to 'unknown'."""
    e = _make_event("panic")
    EventClassifier(provider=_StubProvider()).classify(e)
    assert e.ip_block == "unknown"


def test_ip_block_set_when_provider_returns_value():
    e = _make_event("gpu_event")
    EventClassifier(provider=_ReturningProvider("GUC")).classify(e)
    assert e.ip_block == "GUC"


def test_provider_name_set_correctly():
    e = _make_event("panic")
    EventClassifier(provider=_StubProvider()).classify(e)
    assert e.provider_name == "StubProvider"


# ── Confidence scoring ────────────────────────────────────────────────────────


def test_confidence_higher_with_call_trace():
    """has_call_trace=True should raise confidence vs identical event without."""
    base = _make_event("panic")
    EventClassifier().classify(base)
    conf_without = base.confidence

    with_trace = _make_event("panic", extra_toks=[_tok(2, "call_trace_frame")])
    EventClassifier().classify(with_trace)
    conf_with = with_trace.confidence

    assert conf_with > conf_without


def test_confidence_higher_with_registers():
    """has_registers=True should raise confidence vs identical event without."""
    base = _make_event("panic")
    EventClassifier().classify(base)
    conf_without = base.confidence

    with_regs = _make_event("panic", extra_toks=[_tok(2, "register_dump")])
    EventClassifier().classify(with_regs)
    conf_with = with_regs.confidence

    assert conf_with > conf_without


def test_confidence_higher_with_known_chip_gen():
    """chip_gen != 'unknown' should raise confidence."""
    generic = _make_event("gpu_event", chip_gen="unknown")
    EventClassifier().classify(generic)
    conf_unknown = generic.confidence

    known = _make_event("gpu_event", chip_gen="amd_cdna3")
    EventClassifier().classify(known)
    conf_known = known.confidence

    assert conf_known > conf_unknown


def test_confidence_lower_for_unknown_subsystem():
    """Events with unknown subsystem start at 0.3 vs 0.5 for known."""
    known_sub = _make_event("gpu_event")   # subsystem = "gpu"
    unknown_sub = _make_event("info")      # subsystem = "unknown"

    EventClassifier().classify(known_sub)
    EventClassifier().classify(unknown_sub)

    assert known_sub.confidence > unknown_sub.confidence


def test_confidence_capped_at_1_0():
    """Confidence never exceeds 1.0 regardless of factors."""
    # Maximum possible: known subsystem (0.5) + call_trace (0.2) + registers (0.1)
    # + known chip_gen (0.1) + critical severity (0.1) = 1.0
    toks = [
        _tok(1, "panic", chip_gen="amd_cdna3"),
        _tok(2, "call_trace_frame", chip_gen="amd_cdna3"),
        _tok(3, "register_dump", chip_gen="amd_cdna3"),
    ]
    events = list(assemble(iter(toks), skip_duplicates=False))
    e = events[0]
    EventClassifier().classify(e)
    assert e.confidence <= 1.0


# ── Integration with assembler ────────────────────────────────────────────────


def test_classify_all_events_from_amd_fixture():
    """All events from AMD fixture should be classified without error."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "amd_cdna3_hang.log")
    events = list(classify_all(assemble(tokenize(it))))
    assert len(events) >= 1
    assert all(e.subsystem in {"gpu", "cpu", "memory", "unknown"} for e in events)
    gpu_events = [e for e in events if e.event_type == "gpu_hang"]
    assert len(gpu_events) >= 1
    assert gpu_events[0].subsystem == "gpu"


def test_classify_all_events_from_intel_fixture():
    """All events from Intel fixture should be classified without error."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "intel_pvc_sriovl.log")
    events = list(classify_all(assemble(tokenize(it))))
    assert len(events) >= 1
    subsystems = {e.subsystem for e in events}
    assert "gpu" in subsystems or "interconnect" in subsystems


def test_classify_all_events_from_qcom_fixture():
    """All events from Qualcomm fixture should have remoteproc subsystem."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "qcom_adsp_cdsp_crash.log")
    events = list(classify_all(assemble(tokenize(it))))
    soc_events = [e for e in events if e.event_type == "soc_crash"]
    assert len(soc_events) == 2
    assert all(e.subsystem == "remoteproc" for e in soc_events)


def test_classify_pipeline_open_log_tokenize_assemble_classify():
    """Full pipeline: open_log → tokenize → assemble → classify_all works end-to-end."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "back_to_back_panic.log")
    events = list(classify_all(assemble(tokenize(it))))
    assert len(events) >= 1
    assert all(e.event_type is not None for e in events)
    assert all(0.0 <= e.confidence <= 1.0 for e in events)
    assert all(isinstance(e.subsystem, str) for e in events)


# ── Extra Q4 warning test ─────────────────────────────────────────────────────


def test_warning_within_5_lines_continues_event():
    """Q4 decision: warning within 5 lines of last boundary is absorbed into the event."""
    toks = [
        _tok(1, "panic", raw="Kernel panic"),
        _tok(2, "call_trace_header", raw="Call Trace:"),
        _tok(5, "warning", raw="WARNING: something"),  # gap = 5-1 = 4 ≤ 5
    ]
    events = list(assemble(iter(toks)))
    # warning is absorbed → still 1 event
    assert len(events) == 1
    assert events[0].event_type == "kernel_panic"
    assert len(events[0].tokens) == 3

    # Classify to ensure no crash
    EventClassifier().classify(events[0])
    assert events[0].subsystem == "cpu"
