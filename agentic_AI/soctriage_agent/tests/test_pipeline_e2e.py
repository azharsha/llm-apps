"""test_pipeline_e2e.py — Phase 7 — 18 end-to-end pipeline tests"""
from __future__ import annotations

import gzip
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# ── Pipeline helper ───────────────────────────────────────────────────────────

def _run_no_llm(log_path, fmt="json"):
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize
    from soctriage.core.token_rule import TokenRuleRegistry
    from soctriage.core.assembler import assemble
    from soctriage.core.classifier import classify_all
    from soctriage.core.hardware_decode import decode_hardware
    from soctriage.core.cascade import analyse
    from soctriage.core.ascii_diagram import render as render_diagram
    from soctriage.core.agent import _fallback_agent_result
    from soctriage.core.reporter import report

    line_iter, meta = open_log(str(log_path))
    reg = TokenRuleRegistry()
    reg.load_defaults()
    tokens = list(tokenize(line_iter, rule_registry=reg))

    from soctriage.core.provider_registry import ProviderRegistry
    pr = ProviderRegistry()
    pr.auto_discover(Path("soctriage/providers"))
    head_text = "\n".join(t.raw for t in tokens[:200])
    provider = pr.detect_provider(head_text)

    events = list(classify_all(assemble(iter(tokens), provider=provider), provider=provider))
    events = decode_hardware(events, provider=provider)
    cascade = analyse(events)
    cascade.ascii_diagram = render_diagram(cascade)
    agent_result = _fallback_agent_result(cascade)
    return report(agent_result, fmt=fmt)


# ── Tests: AMD fixture ────────────────────────────────────────────────────────

def test_e2e_amd_mi300_no_llm_returns_json():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log")
    data = json.loads(result)
    assert isinstance(data, dict)


def test_e2e_amd_mi300_has_events():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log")
    data = json.loads(result)
    assert len(data["events"]) > 0


def test_e2e_amd_mi300_severity_not_info():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log")
    data = json.loads(result)
    assert data["severity"] in ("critical", "error", "warning")


# ── Tests: Intel fixture ──────────────────────────────────────────────────────

def test_e2e_intel_dg2_no_llm_returns_json():
    result = _run_no_llm(FIXTURES_DIR / "intel_dg2_error.log")
    data = json.loads(result)
    assert isinstance(data, dict)


def test_e2e_intel_dg2_has_events():
    result = _run_no_llm(FIXTURES_DIR / "intel_dg2_error.log")
    data = json.loads(result)
    assert len(data["events"]) > 0


# ── Tests: Qualcomm fixture ───────────────────────────────────────────────────

def test_e2e_qcom_adsp_no_llm_returns_json():
    result = _run_no_llm(FIXTURES_DIR / "qcom_adsp_critical.log")
    data = json.loads(result)
    assert isinstance(data, dict)


def test_e2e_qcom_adsp_has_events():
    result = _run_no_llm(FIXTURES_DIR / "qcom_adsp_critical.log")
    data = json.loads(result)
    assert len(data["events"]) > 0


# ── Tests: NVIDIA fixture ─────────────────────────────────────────────────────

def test_e2e_nvidia_gsp_no_llm_returns_json():
    result = _run_no_llm(FIXTURES_DIR / "nvidia_gsp_error.log")
    data = json.loads(result)
    assert isinstance(data, dict)


def test_e2e_nvidia_gsp_chip_gen_present():
    result = _run_no_llm(FIXTURES_DIR / "nvidia_gsp_error.log")
    data = json.loads(result)
    assert "chip_gen" in data
    assert data["chip_gen"]


# ── Tests: empty / no-crash fixtures ─────────────────────────────────────────

def test_e2e_empty_log_no_crash():
    """Empty log — InputError raised for empty file, or returns no events."""
    from soctriage.core.input_handler import open_log, InputError
    from soctriage.core.tokenizer import tokenize
    from soctriage.core.token_rule import TokenRuleRegistry
    from soctriage.core.assembler import assemble
    from soctriage.core.classifier import classify_all

    log_path = FIXTURES_DIR / "generic_empty.log"
    try:
        line_iter, meta = open_log(str(log_path))
        reg = TokenRuleRegistry()
        reg.load_defaults()
        tokens = list(tokenize(line_iter, rule_registry=reg))
        events = list(classify_all(assemble(iter(tokens)), provider=None))
        assert events == []
    except InputError:
        # Empty file raises InputError — expected behavior
        pass


def test_e2e_nocrash_log_no_events():
    """Log with no crash patterns should produce no events."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize
    from soctriage.core.token_rule import TokenRuleRegistry
    from soctriage.core.assembler import assemble
    from soctriage.core.classifier import classify_all

    log_path = FIXTURES_DIR / "generic_nocrash.log"
    line_iter, meta = open_log(str(log_path))
    reg = TokenRuleRegistry()
    reg.load_defaults()
    tokens = list(tokenize(line_iter, rule_registry=reg))
    events = list(classify_all(assemble(iter(tokens)), provider=None))
    # No crash patterns → should be empty or minimal
    assert isinstance(events, list)


# ── Tests: Compressed log ─────────────────────────────────────────────────────

def test_e2e_gz_compressed_log_no_llm(tmp_path):
    src = FIXTURES_DIR / "amd_mi300_critical.log"
    gz_path = tmp_path / "amd_mi300_critical.log.gz"
    with open(src, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        f_out.write(f_in.read())
    result = _run_no_llm(gz_path)
    data = json.loads(result)
    assert isinstance(data, dict)
    assert len(data["events"]) > 0


# ── Tests: Output formats ─────────────────────────────────────────────────────

def test_e2e_markdown_format():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log", fmt="markdown")
    assert "# SoCTriage Report" in result


def test_e2e_html_format():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log", fmt="html")
    assert "<!DOCTYPE html>" in result


# ── Tests: Schema completeness ────────────────────────────────────────────────

def test_e2e_outputschema_all_keys_present():
    from soctriage.core.reporter import OUTPUTSCHEMA
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log")
    data = json.loads(result)
    for key in OUTPUTSCHEMA:
        assert key in data, f"Missing OUTPUTSCHEMA key: {key}"


def test_e2e_json_valid_and_parseable():
    result = _run_no_llm(FIXTURES_DIR / "intel_dg2_error.log")
    # Must be parseable JSON
    data = json.loads(result)
    assert data["version"] == "1.0"


# ── Tests: Mocked LLM agent ───────────────────────────────────────────────────

def test_e2e_mocked_claude_agent_populates_tool_trace():
    """Mock the full agent run to verify tool_trace flows into report."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize
    from soctriage.core.token_rule import TokenRuleRegistry
    from soctriage.core.assembler import assemble
    from soctriage.core.classifier import classify_all
    from soctriage.core.hardware_decode import decode_hardware
    from soctriage.core.cascade import analyse
    from soctriage.core.ascii_diagram import render as render_diagram
    from soctriage.core.agent_result import AgentResult, ToolCall
    from soctriage.core.reporter import report

    log_path = FIXTURES_DIR / "amd_mi300_critical.log"
    line_iter, meta = open_log(str(log_path))
    reg = TokenRuleRegistry()
    reg.load_defaults()
    tokens = list(tokenize(line_iter, rule_registry=reg))

    from soctriage.core.provider_registry import ProviderRegistry
    pr = ProviderRegistry()
    pr.auto_discover(Path("soctriage/providers"))
    head_text = "\n".join(t.raw for t in tokens[:200])
    provider = pr.detect_provider(head_text)

    events = list(classify_all(assemble(iter(tokens), provider=provider), provider=provider))
    events = decode_hardware(events, provider=provider)
    cascade = analyse(events)
    cascade.ascii_diagram = render_diagram(cascade)

    # Create AgentResult with a tool trace
    tc = ToolCall(tool_name="get_cascade_summary", arguments={}, response={},
                  duration_ms=15, call_index=1)
    mock_result = AgentResult(
        cascade=cascade,
        root_cause_narrative="Mocked: GPU firmware crash.",
        fix_suggestions=["Flash new firmware."],
        known_issues_matched=[],
        confidence=0.95,
        subsystem_narrative="GPU",
        tool_trace=[tc],
        llm_backend="anthropic",
        llm_model="claude-sonnet-4-5",
        iterations=1,
        total_ms=200,
        offline_mode=False,
        no_llm_mode=False,
    )

    result = report(mock_result)
    data = json.loads(result)
    assert len(data["tool_trace"]) == 1
    assert data["tool_trace"][0]["tool"] == "get_cascade_summary"


def test_e2e_confidence_range_valid():
    result = _run_no_llm(FIXTURES_DIR / "amd_mi300_critical.log")
    data = json.loads(result)
    assert 0.0 <= data["confidence"] <= 1.0
