"""
test_tool_registry.py — Phase 6

20 tests for ToolRegistry, all 10 tools, execute(), schema generation.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from soctriage.core.cascade       import CascadeResult, CascadeEdge
from soctriage.core.assembler     import LogEvent
from soctriage.core.tokenizer     import LogToken
from soctriage.core.tool_registry import AgentContext, Tool, ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_token(token_type: str = "gpu_event", raw: str = "gpu hang") -> LogToken:
    return LogToken(
        line_no=1, raw=raw, token_type=token_type,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(
    event_id: int = 1,
    event_type: str = "gpu_hang",
    subsystem: str = "gpu",
    severity: str = "error",
    ip_block: str = "GFX",
    tokens: list | None = None,
    provider_name: str = "Intel",
    has_call_trace: bool = False,
) -> LogEvent:
    if tokens is None:
        tokens = [_make_token()]
    return LogEvent(
        event_id=event_id, event_type=event_type, severity=severity,
        subsystem=subsystem, ip_block=ip_block, tokens=tokens,
        start_line=1, end_line=1,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        confidence=0.9, raw_text="gpu_hang detected " * 80,  # > 800 chars
        has_call_trace=has_call_trace, has_registers=False,
        provider_name=provider_name,
    )


def _make_cascade(events: list | None = None) -> CascadeResult:
    if events is None:
        events = [_make_event()]
    return CascadeResult(
        events=events, edges=[], root_cause_id=1, root_cause_conf=0.85,
        severity="error", subsystems_hit=["gpu"], chip_gen="intel_gen12",
        arch="x86_64", kernel_ver="6.1",
        ascii_diagram="[1] gpu_hang",
        event_count=len(events), critical_count=0, error_count=len(events),
        analysis_ns=1000, warning_count=0, info_count=0,
    )


def _ctx(events: list | None = None, provider=None) -> AgentContext:
    return AgentContext(cascade=_make_cascade(events), provider=provider)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_registry_has_10_tools():
    reg = ToolRegistry()
    assert len(reg.all_tools()) == 10


def test_all_tool_names_unique():
    reg   = ToolRegistry()
    names = [t.name for t in reg.all_tools()]
    assert len(names) == len(set(names))


def test_get_root_cause_tool_returns_dict():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_root_cause", {}, ctx)
    assert isinstance(result, dict)
    assert result.get("event_type") == "gpu_hang"


def test_get_cascade_chain_tool_returns_list():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_cascade_chain", {}, ctx)
    assert "result" in result
    assert isinstance(result["result"], list)


def test_get_ascii_diagram_tool_returns_string():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_ascii_diagram", {}, ctx)
    assert "result" in result
    assert isinstance(result["result"], str)
    assert "[1] gpu_hang" in result["result"]


def test_get_event_detail_valid_id():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_event_detail", {"event_id": 1}, ctx)
    assert result["event_id"] == 1
    assert result["event_type"] == "gpu_hang"
    assert "raw_text_excerpt" in result


def test_get_event_detail_invalid_id_returns_error():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_event_detail", {"event_id": 999}, ctx)
    assert "error" in result


def test_get_known_issues_with_provider():
    reg      = ToolRegistry()
    provider = MagicMock()
    provider.get_known_issues.return_value = [
        {"issue_id": "INTEL-001", "title": "Test", "fixed_in": "6.2", "workaround": "none"}
    ]
    ctx    = _ctx(provider=provider)
    result = reg.execute("get_known_issues", {}, ctx)
    assert "matched" in result
    assert len(result["matched"]) == 1
    provider.get_known_issues.assert_called_once()


def test_get_known_issues_without_provider():
    reg    = ToolRegistry()
    ctx    = _ctx(provider=None)
    result = reg.execute("get_known_issues", {}, ctx)
    assert result["matched"] == []
    assert "note" in result


def test_get_subsystem_events_gpu():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_subsystem_events", {"subsystem": "gpu"}, ctx)
    assert "result" in result
    events = result["result"]
    assert isinstance(events, list)
    assert len(events) == 1
    assert events[0]["event_type"] == "gpu_hang"


def test_get_subsystem_events_unknown_subsystem():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_subsystem_events", {"subsystem": "storage"}, ctx)
    assert "result" in result
    assert result["result"] == []


def test_get_provider_info_fields():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_provider_info", {}, ctx)
    assert "chip_gen" in result
    assert "arch" in result
    assert "kernel_ver" in result
    assert "provider" in result
    assert result["chip_gen"] == "intel_gen12"


def test_get_ip_blocks_excludes_unknown():
    events = [
        _make_event(event_id=1, ip_block="GFX"),
        _make_event(event_id=2, ip_block="unknown"),
        _make_event(event_id=3, ip_block="GUC"),
    ]
    reg    = ToolRegistry()
    ctx    = _ctx(events=events)
    result = reg.execute("get_ip_blocks", {}, ctx)
    assert "result" in result
    blocks = result["result"]
    assert "GFX" in blocks
    assert "GUC" in blocks
    assert "unknown" not in blocks


def test_get_severity_summary_counts():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_severity_summary", {}, ctx)
    assert result["overall"] == "error"
    assert result["error"] == 1
    assert result["critical"] == 0
    assert result["warning"] == 0
    assert result["info"] == 0
    assert result["total"] == 1


def test_get_call_trace_with_frames():
    tok = _make_token(token_type="call_trace_frame", raw="[] do_panic+0x10/0x20")
    ev  = _make_event(event_id=1, tokens=[tok], has_call_trace=True)
    reg = ToolRegistry()
    ctx = _ctx(events=[ev])
    result = reg.execute("get_call_trace", {"event_id": 1}, ctx)
    assert result["count"] == 1
    assert result["frames"][0] == "[] do_panic+0x10/0x20"


def test_get_call_trace_no_frames_returns_empty():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("get_call_trace", {"event_id": 1}, ctx)
    assert result["count"] == 0
    assert result["frames"] == []


def test_execute_unknown_tool_returns_error_dict():
    reg    = ToolRegistry()
    ctx    = _ctx()
    result = reg.execute("nonexistent_tool", {}, ctx)
    assert "error" in result
    assert "nonexistent_tool" in result["error"]


def test_all_tools_have_description():
    reg = ToolRegistry()
    for tool in reg.all_tools():
        assert tool.description, f"Tool {tool.name} has no description"
        assert len(tool.description) > 5


def test_all_tools_have_openai_schema():
    reg = ToolRegistry()
    for tool in reg.all_tools():
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]


def test_tool_raw_text_excerpt_capped_at_800_chars():
    long_raw = "x" * 1500
    ev  = LogEvent(
        event_id=1, event_type="gpu_hang", severity="error",
        subsystem="gpu", ip_block="GFX",
        tokens=[_make_token()],
        start_line=1, end_line=1,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        confidence=0.9, raw_text=long_raw,
        has_call_trace=False, has_registers=False,
        provider_name="Intel",
    )
    reg    = ToolRegistry()
    ctx    = _ctx(events=[ev])
    result = reg.execute("get_event_detail", {"event_id": 1}, ctx)
    assert len(result["raw_text_excerpt"]) <= 800
