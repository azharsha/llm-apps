"""test_reporter.py — Phase 7 — 30 tests"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from soctriage.core.cascade       import CascadeResult, CascadeEdge
from soctriage.core.assembler     import LogEvent
from soctriage.core.tokenizer     import LogToken
from soctriage.core.agent_result  import AgentResult, ToolCall
from soctriage.core.reporter      import (
    report, OUTPUTSCHEMA, _to_json, _to_markdown, _event_to_dict, _tool_call_to_dict,
    render_json, render_markdown,
)


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
        warning_count=0, info_count=0, ascii_diagram="[gpu_hang]",
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


# ── Tests: report() function ──────────────────────────────────────────────────

def test_report_returns_string():
    result = report(_make_agent_result())
    assert isinstance(result, str)


def test_report_json_default_format():
    result = report(_make_agent_result())
    # Should be valid JSON
    data = json.loads(result)
    assert isinstance(data, dict)


def test_report_writes_to_file_when_output_set(tmp_path):
    out = str(tmp_path / "report.json")
    rendered = report(_make_agent_result(), output=out)
    assert Path(out).exists()
    assert Path(out).read_text(encoding="utf-8") == rendered


def test_report_never_raises_on_empty_result():
    # Even with a minimal/broken-ish result, report should not raise
    try:
        result = report(_make_agent_result())
        assert isinstance(result, str)
    except Exception as e:
        pytest.fail(f"report() raised unexpectedly: {e}")


def test_report_fallback_json_on_render_error():
    ar = _make_agent_result()
    with patch("soctriage.core.html_renderer.render_html", side_effect=RuntimeError("boom")):
        result = report(ar, fmt="html")
    data = json.loads(result)
    assert "error" in data


# ── Tests: JSON output ────────────────────────────────────────────────────────

def test_json_has_all_outputschema_keys():
    data = json.loads(report(_make_agent_result()))
    for key in OUTPUTSCHEMA:
        assert key in data, f"Missing key: {key}"


def test_json_version_is_1_0():
    data = json.loads(report(_make_agent_result()))
    assert data["version"] == "1.0"


def test_json_provider_correct():
    data = json.loads(report(_make_agent_result()))
    assert data["provider"] == "amd"


def test_json_chip_gen_correct():
    data = json.loads(report(_make_agent_result()))
    assert data["chip_gen"] == "amd_cdna3"


def test_json_events_is_list():
    data = json.loads(report(_make_agent_result()))
    assert isinstance(data["events"], list)
    assert len(data["events"]) == 1


def test_json_cascade_has_root_cause():
    data = json.loads(report(_make_agent_result()))
    assert "cascade" in data
    cascade = data["cascade"]
    assert "root_cause" in cascade


def test_json_confidence_between_0_and_1():
    data = json.loads(report(_make_agent_result()))
    conf = data["confidence"]
    assert 0.0 <= conf <= 1.0


def test_json_include_raw_adds_raw_text():
    data = json.loads(report(_make_agent_result(), include_raw=True))
    event = data["events"][0]
    assert "raw_text" in event
    assert event["raw_text"] == "GPU HANG detected"


# ── Tests: hardware key ───────────────────────────────────────────────────────

def test_hardware_key_present_when_context_exists():
    ar = _make_agent_result()
    mock_hw = MagicMock()
    mock_hw.to_dict.return_value = {"stall_type": "firmware_boot_fail"}
    ar.cascade.events[0].__dict__["hardware_context"] = mock_hw
    data = json.loads(report(ar))
    assert data["hardware"] == [{"stall_type": "firmware_boot_fail"}]


def test_hardware_key_empty_list_when_no_context():
    data = json.loads(report(_make_agent_result()))
    assert data["hardware"] == []


def test_hardware_context_accessed_via_dict_get():
    ar = _make_agent_result()
    # Verify no hardware_context attribute → empty list
    event = ar.cascade.events[0]
    assert event.__dict__.get("hardware_context") is None
    data = json.loads(report(ar))
    assert data["hardware"] == []


# ── Tests: Markdown output ────────────────────────────────────────────────────

def test_markdown_has_h1_header():
    result = report(_make_agent_result(), fmt="markdown")
    assert "# SoCTriage Report" in result


def test_markdown_has_root_cause_section():
    result = report(_make_agent_result(), fmt="markdown")
    assert "Root Cause" in result
    assert "GPU hang due to firmware failure." in result


def test_markdown_has_fix_suggestions():
    result = report(_make_agent_result(), fmt="markdown")
    assert "Update firmware." in result


def test_markdown_has_ascii_diagram():
    result = report(_make_agent_result(), fmt="markdown")
    assert "[gpu_hang]" in result


def test_markdown_has_known_issues_when_matched():
    ar = _make_agent_result()
    ar.known_issues_matched = [{"issue_id": "BUG-001", "title": "GPU hang on boot", "fixed_in": "6.9", "workaround": "none"}]
    result = report(ar, fmt="markdown")
    assert "BUG-001" in result


def test_markdown_severity_in_header():
    result = report(_make_agent_result(severity="error"), fmt="markdown")
    assert "ERROR" in result


# ── Tests: HTML output ────────────────────────────────────────────────────────

def test_html_has_doctype():
    result = report(_make_agent_result(), fmt="html")
    assert "<!DOCTYPE html>" in result


def test_html_has_severity_badge():
    result = report(_make_agent_result(severity="error"), fmt="html")
    assert "ERROR" in result
    assert "badge" in result


def test_html_no_external_dependencies():
    result = report(_make_agent_result(), fmt="html")
    # No http:// or https:// references to external resources
    import re
    external = re.findall(r'(src|href)\s*=\s*["\']https?://', result)
    assert not external, f"Found external dependencies: {external}"


# ── Tests: schema completeness ────────────────────────────────────────────────

def test_all_outputschema_keys_present_in_json():
    data = json.loads(report(_make_agent_result()))
    for key in OUTPUTSCHEMA:
        assert key in data


def test_no_extra_keys_outside_schema():
    data = json.loads(report(_make_agent_result()))
    for key in data:
        assert key in OUTPUTSCHEMA, f"Unexpected key in output: {key}"


def test_tool_trace_serialised_correctly():
    ar = _make_agent_result()
    tc = ToolCall(tool_name="get_cascade", arguments={"foo": "bar"},
                  response={"ok": True}, duration_ms=5, call_index=1)
    ar.tool_trace = [tc]
    data = json.loads(report(ar))
    assert len(data["tool_trace"]) == 1
    entry = data["tool_trace"][0]
    assert entry["tool"] == "get_cascade"
    assert entry["index"] == 1
    assert entry["duration_ms"] == 5


def test_analysis_ms_is_integer():
    data = json.loads(report(_make_agent_result()))
    assert isinstance(data["analysis_ms"], int)


def test_xfail06_report_stub_now_passes():
    """XFAIL-06: report() stub must now return non-empty string without raising."""
    result = report(_make_agent_result())
    assert result
    assert len(result) > 0
