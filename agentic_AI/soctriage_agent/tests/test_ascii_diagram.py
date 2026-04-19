"""
test_ascii_diagram.py — Phase 4 v4.0.0
10 tests for the ASCII cascade diagram renderer.
Expected: 10 PASSED, 0 FAILED
"""

from __future__ import annotations

import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.cascade import CascadeEdge, CascadeResult, analyse
from soctriage.core.ascii_diagram import render
from soctriage.core.tokenizer import LogToken


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(line_no: int, chip_gen: str = "unknown", arch: str = "unknown") -> LogToken:
    return LogToken(
        line_no=line_no, raw="test", token_type="unknown",
        arch=arch, chip_gen=chip_gen, kernel_ver=None,
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(
    event_id: int,
    event_type: str,
    severity: str,
    subsystem: str = "gpu",
    start_line: int = 1,
    end_line: int = 5,
    chip_gen: str = "unknown",
    arch: str = "unknown",
    confidence: float = 0.7,
) -> LogEvent:
    tok = _tok(start_line, chip_gen=chip_gen, arch=arch)
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
        kernel_ver="6.8.0-45",
        confidence=confidence,
        raw_text="test line",
        has_call_trace=False,
        has_registers=False,
        provider_name="generic",
    )


def _empty_result() -> CascadeResult:
    return CascadeResult(
        events=[], edges=[], root_cause_id=None, root_cause_conf=0.0,
        severity="info", subsystems_hit=[], chip_gen="unknown",
        arch="unknown", kernel_ver=None, ascii_diagram="",
        event_count=0, critical_count=0, error_count=0, analysis_ns=0,
    )


def _single_event_result() -> CascadeResult:
    ev = _make_event(1, "gpu_hang", "critical", "gpu")
    return CascadeResult(
        events=[ev], edges=[], root_cause_id=ev.event_id, root_cause_conf=0.61,
        severity="critical", subsystems_hit=["gpu"], chip_gen="unknown",
        arch="x86_64", kernel_ver="6.8.0-45", ascii_diagram="",
        event_count=1, critical_count=1, error_count=0, analysis_ns=100,
    )


def _two_event_chain_result() -> CascadeResult:
    e1 = _make_event(1, "firmware_fail", "error",    "firmware", start_line=1, end_line=10)
    e2 = _make_event(2, "gpu_hang",      "critical", "gpu",      start_line=15, end_line=30)
    edge = CascadeEdge(
        source_id=1, target_id=2,
        relation="causes", confidence=0.90,
        reasoning="GuC/HuC firmware not loaded → ring timeout",
    )
    return CascadeResult(
        events=[e1, e2], edges=[edge], root_cause_id=1, root_cause_conf=0.84,
        severity="critical", subsystems_hit=["firmware", "gpu"],
        chip_gen="intel_dg2", arch="x86_64", kernel_ver="6.8.0-45",
        ascii_diagram="", event_count=2, critical_count=1, error_count=1,
        analysis_ns=500,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_render_returns_string():
    result = _single_event_result()
    output = render(result)
    assert isinstance(output, str)
    assert len(output) > 0


def test_render_contains_root_cause_marker():
    result = _single_event_result()
    output = render(result)
    assert "ROOT CAUSE" in output


def test_render_contains_chip_gen():
    e1 = _make_event(1, "gpu_hang", "critical", "gpu", chip_gen="intel_dg2")
    result = CascadeResult(
        events=[e1], edges=[], root_cause_id=1, root_cause_conf=0.61,
        severity="critical", subsystems_hit=["gpu"], chip_gen="intel_dg2",
        arch="x86_64", kernel_ver="6.8.0-45", ascii_diagram="",
        event_count=1, critical_count=1, error_count=0, analysis_ns=0,
    )
    output = render(result)
    assert "intel_dg2" in output


def test_render_contains_severity_footer():
    result = _single_event_result()
    output = render(result)
    assert "CRITICAL" in output
    # Footer summary line with severity
    assert "Severity" in output


def test_render_single_event_no_connector():
    result = _single_event_result()
    output = render(result)
    # No connector arrows for a single event
    assert "▼" not in output
    # Root cause marker present
    assert "ROOT CAUSE" in output


def test_render_two_event_chain_has_arrow():
    result = _two_event_chain_result()
    output = render(result)
    assert "▼" in output
    assert "│" in output
    assert "causes" in output


def test_render_subsystem_chain_in_footer():
    result = _two_event_chain_result()
    output = render(result)
    assert "firmware" in output
    assert "gpu" in output
    # Footer shows subsystem chain with arrows
    assert "→" in output


def test_render_empty_result_no_crash():
    result = _empty_result()
    output = render(result)
    # Must not raise, must return a string
    assert isinstance(output, str)
    assert "SoCTriage Cascade Analysis" in output


def test_render_unicode_box_chars_present():
    result = _single_event_result()
    output = render(result)
    assert "╔" in output
    assert "╗" in output
    assert "╚" in output
    assert "╝" in output
    assert "║" in output
    assert "═" in output


def test_render_line_width_under_80_chars():
    result = _two_event_chain_result()
    output = render(result)
    for i, line in enumerate(output.splitlines()):
        assert len(line) < 80, f"Line {i} is {len(line)} chars: {line!r}"
