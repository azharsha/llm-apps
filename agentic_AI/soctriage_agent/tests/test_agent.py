"""
test_agent.py — Phase 6

30 tests for SoCTriageAgent, run_agent(), fallback, edge cases, fixture integration.
All LLM calls are mocked — no live network required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from soctriage.core.cascade       import CascadeResult, CascadeEdge
from soctriage.core.assembler     import LogEvent
from soctriage.core.tokenizer     import LogToken
from soctriage.core.agent_result  import AgentResult, ToolCall
from soctriage.core.tool_registry import AgentContext, ToolRegistry
from soctriage.core.llm_client    import LLMResponse, ToolCallRequest
from soctriage.core.agent         import (
    SoCTriageAgent, run_agent,
    _fallback_agent_result, _parse_agent_result,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"


# ── Builders ──────────────────────────────────────────────────────────────────


def _make_token(line_no: int = 1, raw: str = "gpu_hang",
                token_type: str = "gpu_event") -> LogToken:
    return LogToken(
        line_no=line_no, raw=raw, token_type=token_type,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        timestamp=None, is_duplicate=False, confidence=1.0,
    )


def _make_event(
    event_id: int = 1,
    event_type: str = "gpu_hang",
    subsystem: str = "gpu",
    severity: str = "error",
    provider_name: str = "Intel",
    has_call_trace: bool = False,
) -> LogEvent:
    return LogEvent(
        event_id=event_id, event_type=event_type, severity=severity,
        subsystem=subsystem, ip_block="GFX",
        tokens=[_make_token()],
        start_line=1, end_line=1,
        arch="x86_64", chip_gen="intel_gen12", kernel_ver="6.1",
        confidence=0.9, raw_text="gpu_hang detected",
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


def _empty_cascade() -> CascadeResult:
    return CascadeResult(
        events=[], edges=[], root_cause_id=None, root_cause_conf=0.0,
        severity="info", subsystems_hit=[], chip_gen="unknown",
        arch="unknown", kernel_ver=None,
        ascii_diagram="",
        event_count=0, critical_count=0, error_count=0,
        analysis_ns=0, warning_count=0, info_count=0,
    )


def _stop_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=[], stop_reason="end_turn", usage={}
    )


def _tool_call_response(tool_name: str = "get_root_cause", args: dict | None = None,
                         tc_id: str = "toolu_01") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id=tc_id, tool_name=tool_name, arguments=args or {})],
        stop_reason="tool_use",
        usage={},
    )


_FINAL_JSON = json.dumps({
    "root_cause_narrative": "GPU hang due to firmware failure.",
    "fix_suggestions": ["Update firmware.", "Check GuC logs."],
    "known_issues_matched": [],
    "confidence": 0.88,
    "subsystem_narrative": "GPU subsystem hung.",
})


def _make_mock_llm(responses: list[LLMResponse]) -> MagicMock:
    mock = MagicMock()
    mock.chat.side_effect = responses
    mock._model           = "claude-sonnet-4-5"
    return mock


# ── AgentResult + ToolCall dataclass tests ────────────────────────────────────


def test_agent_result_importable():
    """AgentResult and ToolCall should be importable from agent_result."""
    from soctriage.core.agent_result import AgentResult, ToolCall
    assert AgentResult is not None
    assert ToolCall is not None


def test_tool_call_fields():
    tc = ToolCall(
        tool_name="get_root_cause", arguments={},
        response={"event_type": "gpu_hang"},
        duration_ms=5, call_index=1,
    )
    assert tc.tool_name == "get_root_cause"
    assert tc.call_index == 1
    assert tc.duration_ms == 5


def test_agent_result_to_dict_json_serialisable():
    cascade = _make_cascade()
    result  = _fallback_agent_result(cascade)
    d       = result.to_dict()
    # Must be JSON-serialisable (no dataclass objects inside)
    serialised = json.dumps(d)
    assert isinstance(serialised, str)
    assert len(serialised) > 50


def test_agent_result_to_markdown_returns_string():
    cascade = _make_cascade()
    result  = _fallback_agent_result(cascade)
    md      = result.to_markdown()
    assert isinstance(md, str)
    assert "## SoCTriage Analysis" in md


# ── Happy path tests ──────────────────────────────────────────────────────────


def test_agent_run_returns_agent_result():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)


def test_agent_calls_get_root_cause_first():
    """The agent should make at least one tool call; root cause is the first tool."""
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        _tool_call_response("get_root_cause"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    # Tool trace should contain get_root_cause
    tool_names = [tc.tool_name for tc in result.tool_trace]
    assert "get_root_cause" in tool_names


def test_agent_calls_get_known_issues():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        _tool_call_response("get_known_issues"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    tool_names = [tc.tool_name for tc in result.tool_trace]
    assert "get_known_issues" in tool_names


def test_agent_calls_get_call_trace_on_panic():
    ev      = _make_event(event_id=1, event_type="kernel_panic",
                          subsystem="cpu", has_call_trace=True)
    cascade = _make_cascade(events=[ev])
    mock_llm = _make_mock_llm([
        _tool_call_response("get_call_trace", {"event_id": 1}, "tc1"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    tool_names = [tc.tool_name for tc in result.tool_trace]
    assert "get_call_trace" in tool_names


def test_agent_stops_at_stop_reason():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert result.no_llm_mode is False
    assert result.root_cause_narrative == "GPU hang due to firmware failure."


def test_tool_trace_populated():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        _tool_call_response("get_root_cause"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert len(result.tool_trace) >= 1
    assert result.tool_trace[0].call_index == 1


def test_agent_result_confidence_in_range():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert 0.0 <= result.confidence <= 1.0


def test_agent_result_fix_suggestions_not_empty():
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result.fix_suggestions, list)
    assert len(result.fix_suggestions) > 0


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_ec28_llm_timeout_fallback():
    """EC-28: LLM raises an exception → fallback result with no_llm_mode=True."""
    cascade  = _make_cascade()
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = Exception("timeout")
    mock_llm._model = "claude-sonnet-4-5"
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is True
    assert result.iterations == 0
    assert "timeout" not in result.root_cause_narrative  # error text must not leak


def test_ec29_no_tool_calls_reprompt():
    """EC-29: LLM returns content without tool_calls on first turn — agent stops."""
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([_stop_response("No tool calls here.")])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    # Should complete without crashing
    assert result.root_cause_narrative == "No tool calls here."


def test_ec30_max_iterations_enforced():
    """EC-30: Loop stops at MAX_ITERATIONS even if LLM keeps requesting tool calls."""
    cascade = _make_cascade()
    # Always return a tool call response — agent must stop at 8
    mock_llm = MagicMock()
    mock_llm.chat.return_value = _tool_call_response("get_root_cause")
    mock_llm._model = "claude-sonnet-4-5"
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.iterations == SoCTriageAgent.MAX_ITERATIONS


def test_ec31_unknown_tool_name_no_crash():
    """EC-31: LLM requests unknown tool → execute returns error dict, loop continues."""
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        _tool_call_response("nonexistent_tool", {}, "tc1"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    # nonexistent_tool should appear in trace with error response
    assert any(tc.tool_name == "nonexistent_tool" for tc in result.tool_trace)
    error_tc = next(tc for tc in result.tool_trace if tc.tool_name == "nonexistent_tool")
    assert "error" in error_tc.response


def test_ec32_no_llm_mode_returns_fallback():
    """EC-32: run_agent(no_llm=True) returns fallback without LLM call."""
    cascade = _make_cascade()
    result  = run_agent(cascade, no_llm=True)
    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is True
    assert result.llm_backend == "none"
    assert result.iterations == 0


def test_ec33_ollama_not_running_fallback():
    """EC-33: Ollama not running → ConnectError → fallback result."""
    cascade = _make_cascade()
    try:
        import httpx
        error_class = httpx.ConnectError
        error_inst  = error_class("Connection refused")
    except ImportError:
        error_inst = Exception("Connection refused")

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = error_inst
    mock_llm._model = "llama3:8b"
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is True


def test_ec34_empty_cascade_runs_cleanly():
    """EC-34: Empty cascade (0 events) — agent returns valid AgentResult."""
    cascade  = _empty_cascade()
    mock_llm = _make_mock_llm([
        _stop_response("No events found in cascade. Cannot determine root cause.")
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.root_cause_narrative is not None


def test_fallback_result_is_valid_agent_result():
    """_fallback_agent_result() produces a valid AgentResult."""
    cascade = _make_cascade()
    result  = _fallback_agent_result(cascade, error="test error")
    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is True
    assert result.llm_backend == "none"
    assert result.confidence >= 0.0
    assert "test error" in result.root_cause_narrative


# ── Fixture integration ───────────────────────────────────────────────────────


def _cascade_from_fixture(fixture_path: Path) -> CascadeResult:
    """Load a fixture JSON and build a minimal CascadeResult from it."""
    import json as _json
    data    = _json.loads(fixture_path.read_text())
    summary = data.get("summary", {})
    rc_data = data.get("root_cause")

    events: list[LogEvent] = []
    if rc_data:
        tok = LogToken(
            line_no=rc_data.get("start_line", 1),
            raw=rc_data.get("raw_text", ""),
            token_type="gpu_event",
            arch=summary.get("arch", "unknown"),
            chip_gen=summary.get("chip_gen", "unknown"),
            kernel_ver=summary.get("kernel_ver"),
            timestamp=None, is_duplicate=False, confidence=1.0,
        )
        ev = LogEvent(
            event_id=rc_data["event_id"],
            event_type=rc_data["event_type"],
            severity=rc_data.get("severity", "error"),
            subsystem=rc_data.get("subsystem", "unknown"),
            ip_block="unknown",
            tokens=[tok],
            start_line=rc_data.get("start_line", 1),
            end_line=rc_data.get("end_line", 1),
            arch=summary.get("arch", "unknown"),
            chip_gen=summary.get("chip_gen", "unknown"),
            kernel_ver=summary.get("kernel_ver"),
            confidence=rc_data.get("confidence", 0.5),
            raw_text=rc_data.get("raw_text", ""),
            has_call_trace=False, has_registers=False,
            provider_name="generic",
        )
        events.append(ev)

    rc_id   = rc_data["event_id"] if rc_data else None
    rc_conf = rc_data.get("confidence", 0.0) if rc_data else 0.0
    return CascadeResult(
        events=events, edges=[],
        root_cause_id=rc_id, root_cause_conf=rc_conf,
        severity=summary.get("severity", "info"),
        subsystems_hit=summary.get("subsystems_hit", []),
        chip_gen=summary.get("chip_gen", "unknown"),
        arch=summary.get("arch", "unknown"),
        kernel_ver=summary.get("kernel_ver"),
        ascii_diagram=data.get("ascii_diagram", ""),
        event_count=summary.get("event_count", len(events)),
        critical_count=summary.get("critical_count", 0),
        error_count=summary.get("error_count", 0),
        analysis_ns=0,
        warning_count=summary.get("warning_count", 0),
        info_count=summary.get("info_count", 0),
    )


def test_intel_dg2_guc_fixture_agent_run():
    cascade  = _cascade_from_fixture(FIXTURES_DIR / "intel_dg2_guc.json")
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.cascade.chip_gen == "intel_gen12"


def test_amd_mi300_fixture_agent_run():
    cascade  = _cascade_from_fixture(FIXTURES_DIR / "amd_mi300_mmhub.json")
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.cascade.chip_gen == "amd_cdna3"


def test_qcom_adsp_fixture_ollama_mock():
    cascade  = _cascade_from_fixture(FIXTURES_DIR / "qcom_adsp_panic.json")
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    mock_llm._model = "llama3:8b"
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.cascade.chip_gen == "qcom_sm8550"


def test_nvidia_gsp_fixture_agent_run():
    cascade  = _cascade_from_fixture(FIXTURES_DIR / "nvidia_gsp_timeout.json")
    mock_llm = _make_mock_llm([_stop_response(_FINAL_JSON)])
    agent    = SoCTriageAgent(mock_llm, ToolRegistry())
    result   = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.cascade.chip_gen == "nvidia_h100"


def test_generic_fallback_fixture():
    cascade = _cascade_from_fixture(FIXTURES_DIR / "generic_unknown.json")
    result  = run_agent(cascade, no_llm=True)
    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is True


def test_full_pipeline_open_log_to_agent_result():
    """End-to-end: cascade → agent → AgentResult with mocked LLM."""
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        _tool_call_response("get_root_cause"),
        _tool_call_response("get_known_issues"),
        _stop_response(_FINAL_JSON),
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    md = result.to_markdown()
    assert "## SoCTriage Analysis" in md
    assert result.confidence > 0.0


# ── run_agent() entry point ───────────────────────────────────────────────────


def test_run_agent_no_llm_flag():
    cascade = _make_cascade()
    result  = run_agent(cascade, no_llm=True)
    assert result.no_llm_mode is True
    assert result.llm_backend == "none"


def test_run_agent_anthropic_backend():
    """run_agent with anthropic backend calls AnthropicClient (mocked)."""
    cascade = _make_cascade()
    mock_llm_instance = _make_mock_llm([_stop_response(_FINAL_JSON)])

    with patch("soctriage.core.agent.AnthropicClient", return_value=mock_llm_instance):
        result = run_agent(cascade, backend="anthropic", model="claude-sonnet-4-5")

    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is False


def test_run_agent_ollama_backend():
    """run_agent with ollama backend calls OllamaClient (mocked)."""
    cascade = _make_cascade()
    mock_llm_instance = _make_mock_llm([_stop_response(_FINAL_JSON)])

    with patch("soctriage.core.agent.OllamaClient", return_value=mock_llm_instance):
        result = run_agent(cascade, backend="ollama", model="llama3:8b")

    assert isinstance(result, AgentResult)
    assert result.no_llm_mode is False


def test_run_agent_returns_agent_result_type():
    cascade = _make_cascade()
    result  = run_agent(cascade, no_llm=True)
    assert isinstance(result, AgentResult)
    # Verify all required fields are present
    assert hasattr(result, "cascade")
    assert hasattr(result, "root_cause_narrative")
    assert hasattr(result, "fix_suggestions")
    assert hasattr(result, "known_issues_matched")
    assert hasattr(result, "confidence")
    assert hasattr(result, "tool_trace")
    assert hasattr(result, "llm_backend")
    assert hasattr(result, "no_llm_mode")


def test_length_stop_reason_returns_partial_result():
    """stop_reason='max_tokens' should break loop and return partial result."""
    cascade  = _make_cascade()
    mock_llm = _make_mock_llm([
        LLMResponse(content="partial truncated text", tool_calls=[], stop_reason="max_tokens", usage={})
    ])
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert isinstance(result, AgentResult)
    assert result.root_cause_narrative == "partial truncated text"
    assert result.no_llm_mode is False


def test_parse_agent_result_markdown_fence_stripped():
    """LLM response wrapped in ```json fences should be parsed correctly."""
    cascade = _make_cascade()
    fenced  = "```json\n" + _FINAL_JSON + "\n```"
    result  = _parse_agent_result(fenced, cascade, [], 1, 100)
    assert result.root_cause_narrative == "GPU hang due to firmware failure."
    assert result.fix_suggestions == ["Update firmware.", "Check GuC logs."]


def test_parse_agent_result_fix_suggestions_string_coerced():
    """LLM returning fix_suggestions as a string should be wrapped in a list."""
    cascade = _make_cascade()
    bad_json = json.dumps({
        "root_cause_narrative": "firmware timeout",
        "fix_suggestions": "update the firmware",
        "confidence": 0.7,
        "subsystem_narrative": "",
    })
    result = _parse_agent_result(bad_json, cascade, [], 1, 100)
    assert isinstance(result.fix_suggestions, list)
    assert result.fix_suggestions == ["update the firmware"]


def test_llm_exception_does_not_leak_error_message():
    """Exception message should not appear in root_cause_narrative (no secret leakage)."""
    cascade  = _make_cascade()
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = Exception("Authentication failed: invalid API key sk-secret123")
    mock_llm._model = "claude-sonnet-4-5"
    agent  = SoCTriageAgent(mock_llm, ToolRegistry())
    result = agent.run(cascade)
    assert result.no_llm_mode is True
    assert "sk-secret123" not in result.root_cause_narrative
    assert "Authentication" not in result.root_cause_narrative
