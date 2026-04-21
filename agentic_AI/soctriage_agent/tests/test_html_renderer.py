"""test_html_renderer.py — Phase 7 — 12 tests"""
from __future__ import annotations

import pytest

from soctriage.core.cascade       import CascadeResult, CascadeEdge
from soctriage.core.assembler     import LogEvent
from soctriage.core.tokenizer     import LogToken
from soctriage.core.agent_result  import AgentResult, ToolCall
from soctriage.core.html_renderer import render_html


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(raw: str = "GPU HANG", line: int = 1) -> LogToken:
    return LogToken(
        token_type="gpu_event", raw=raw, line_no=line,
        arch="x86_64", chip_gen="amd_cdna3", kernel_ver="6.8.0",
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(event_id: int = 1, severity: str = "error",
                event_type: str = "gpu_hang") -> LogEvent:
    tok = _make_token()
    return LogEvent(
        event_id=event_id, event_type=event_type, severity=severity,
        subsystem="gpu", ip_block="gfx", tokens=[tok],
        start_line=1, end_line=3, arch="x86_64", chip_gen="amd_cdna3",
        kernel_ver="6.8.0", confidence=0.85, raw_text="GPU HANG detected",
        has_call_trace=False, has_registers=False, provider_name="amd",
    )


def _make_cascade(severity: str = "error") -> CascadeResult:
    ev = _make_event(severity=severity)
    return CascadeResult(
        events=[ev], edges=[], root_cause_id=1, root_cause_conf=0.85,
        chip_gen="amd_cdna3", arch="x86_64", kernel_ver="6.8.0",
        severity=severity, subsystems_hit=["gpu"],
        event_count=1, critical_count=0, error_count=1,
        warning_count=0, info_count=0, ascii_diagram="[gpu_hang] --> [firmware_fail]",
        analysis_ns=100_000,
    )


def _make_agent_result(severity: str = "error") -> AgentResult:
    cascade = _make_cascade(severity=severity)
    return AgentResult(
        cascade=cascade,
        root_cause_narrative="GPU hang due to firmware failure.",
        fix_suggestions=["Update firmware.", "Check GuC logs."],
        known_issues_matched=[],
        confidence=0.88,
        subsystem_narrative="GPU subsystem hung.",
        tool_trace=[],
        llm_backend="none",
        llm_model="none",
        iterations=0,
        total_ms=42,
        offline_mode=False,
        no_llm_mode=True,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_render_html_returns_string():
    result = render_html(_make_agent_result())
    assert isinstance(result, str)


def test_html5_doctype_present():
    result = render_html(_make_agent_result())
    assert "<!DOCTYPE html>" in result


def test_chip_gen_in_header():
    result = render_html(_make_agent_result())
    assert "amd_cdna3" in result


def test_severity_badge_colour_critical():
    result = render_html(_make_agent_result(severity="critical"))
    assert "#D32F2F" in result


def test_severity_badge_colour_error():
    result = render_html(_make_agent_result(severity="error"))
    assert "#E64A19" in result


def test_severity_badge_colour_warning():
    result = render_html(_make_agent_result(severity="warning"))
    assert "#F57C00" in result


def test_root_cause_in_highlight_box():
    result = render_html(_make_agent_result())
    assert "root-cause" in result
    assert "GPU hang due to firmware failure." in result


def test_fix_suggestions_in_ol():
    result = render_html(_make_agent_result())
    assert "<ol>" in result
    assert "<li>Update firmware.</li>" in result


def test_known_issues_as_cards():
    ar = _make_agent_result()
    ar.known_issues_matched = [
        {"issue_id": "BUG-42", "title": "GPU stall on boot", "fixed_in": "6.9", "workaround": "reboot"}
    ]
    result = render_html(ar)
    assert "issue-card" in result
    assert "BUG-42" in result


def test_events_table_has_all_columns():
    result = render_html(_make_agent_result())
    for col in ["Subsystem", "IP Block", "Severity", "Conf"]:
        assert col in result


def test_tool_trace_in_details_element():
    ar = _make_agent_result()
    tc = ToolCall(tool_name="get_cascade", arguments={"x": 1},
                  response={}, duration_ms=10, call_index=1)
    ar.tool_trace = [tc]
    result = render_html(ar)
    assert "<details>" in result


def test_ascii_diagram_in_pre_monospace():
    result = render_html(_make_agent_result())
    assert "monospace" in result
    assert "[gpu_hang]" in result
