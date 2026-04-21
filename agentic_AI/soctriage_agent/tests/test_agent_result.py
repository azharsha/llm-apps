"""
test_agent_result.py — Phase 6

10 tests for AgentResult and ToolCall dataclasses, to_dict(), to_markdown().
"""

from __future__ import annotations

import json
import pytest

from soctriage.core.cascade       import CascadeResult, CascadeEdge
from soctriage.core.assembler     import LogEvent
from soctriage.core.tokenizer     import LogToken
from soctriage.core.agent_result  import AgentResult, ToolCall


# ── Helper builders ───────────────────────────────────────────────────────────


def _make_token(line_no: int = 1, raw: str = "gpu_hang detected",
                token_type: str = "gpu_event") -> LogToken:
    return LogToken(
        line_no=line_no, raw=raw, token_type=token_type,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(event_id: int = 1, event_type: str = "gpu_hang",
                subsystem: str = "gpu", severity: str = "error",
                provider_name: str = "Intel") -> LogEvent:
    return LogEvent(
        event_id=event_id, event_type=event_type, severity=severity,
        subsystem=subsystem, ip_block="GFX",
        tokens=[_make_token()],
        start_line=1, end_line=1,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        confidence=0.9, raw_text="gpu_hang detected",
        has_call_trace=False, has_registers=False,
        provider_name=provider_name,
    )


def _make_cascade() -> CascadeResult:
    ev = _make_event()
    return CascadeResult(
        events=[ev], edges=[], root_cause_id=1, root_cause_conf=0.85,
        severity="error", subsystems_hit=["gpu"], chip_gen="intel_gen12",
        arch="x86_64", kernel_ver="6.1",
        ascii_diagram="[1] gpu_hang",
        event_count=1, critical_count=0, error_count=1,
        analysis_ns=1000, warning_count=0, info_count=0,
    )


def _make_tool_call(idx: int = 1) -> ToolCall:
    return ToolCall(
        tool_name="get_root_cause", arguments={},
        response={"event_type": "gpu_hang"},
        duration_ms=5, call_index=idx,
    )


def _make_agent_result(*, offline: bool = False, no_llm: bool = False) -> AgentResult:
    cascade = _make_cascade()
    return AgentResult(
        cascade=cascade,
        root_cause_narrative="GPU hang caused by firmware failure.",
        fix_suggestions=["Update firmware.", "Check GuC logs."],
        known_issues_matched=[
            {
                "issue_id": "INTEL-DG2-001",
                "title": "GuC firmware load failure",
                "fixed_in": "linux-firmware-20231030",
                "workaround": "Set i915.enable_guc=3",
            }
        ],
        confidence=0.88,
        subsystem_narrative="GPU subsystem hung after firmware failure.",
        tool_trace=[_make_tool_call(1)],
        llm_backend="openai",
        llm_model="gpt-4o",
        iterations=3,
        total_ms=420,
        offline_mode=offline,
        no_llm_mode=no_llm,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_to_dict_root_cause_present():
    ar = _make_agent_result()
    d  = ar.to_dict()
    assert "cascade" in d
    assert d["cascade"]["root_cause"] is not None
    assert d["cascade"]["root_cause"]["event_type"] == "gpu_hang"


def test_to_dict_cascade_chain_present():
    ar = _make_agent_result()
    d  = ar.to_dict()
    assert "cascade" in d
    assert isinstance(d["cascade"]["cascade"], list)


def test_to_markdown_has_root_cause_section():
    ar = _make_agent_result()
    md = ar.to_markdown()
    assert "### Root Cause" in md
    assert "GPU hang caused by firmware failure." in md


def test_to_markdown_has_fix_suggestions():
    ar = _make_agent_result()
    md = ar.to_markdown()
    assert "### Fix Suggestions" in md
    assert "Update firmware." in md


def test_to_markdown_has_ascii_diagram():
    ar = _make_agent_result()
    md = ar.to_markdown()
    assert "### Cascade Diagram" in md
    assert "[1] gpu_hang" in md


def test_to_markdown_has_tool_trace():
    ar = _make_agent_result()
    md = ar.to_markdown()
    assert "### Tool Call Trace" in md
    assert "get_root_cause" in md


def test_to_markdown_has_known_issues_when_matched():
    ar = _make_agent_result()
    md = ar.to_markdown()
    assert "### Known Issues Matched" in md
    assert "INTEL-DG2-001" in md
    assert "GuC firmware load failure" in md


def test_confidence_between_0_and_1():
    ar = _make_agent_result()
    assert 0.0 <= ar.confidence <= 1.0


def test_offline_mode_flag_set_correctly():
    ar = _make_agent_result(offline=True)
    assert ar.offline_mode is True
    assert ar.no_llm_mode is False


def test_no_llm_mode_flag_set_correctly():
    ar = _make_agent_result(no_llm=True)
    assert ar.no_llm_mode is True
    assert ar.offline_mode is False
