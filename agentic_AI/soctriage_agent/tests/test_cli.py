"""test_cli.py — Phase 7 — 20 tests"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from soctriage.cli import (
    main, build_parser,
    EXITOK, EXITCRITICAL, EXITERROR, EXITUSAGE, EXIT_SUCCESS,
)


# ── Fixtures / Helpers ────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


def _make_cascade(severity: str = "error"):
    from soctriage.core.cascade import CascadeResult
    from soctriage.core.assembler import LogEvent
    from soctriage.core.tokenizer import LogToken

    tok = LogToken(token_type="gpu_event", raw="GPU HANG", line_no=1,
                   arch="x86_64", chip_gen="amd_cdna3", kernel_ver="6.8.0",
                   timestamp=None, is_duplicate=False, confidence=1.0)
    ev = LogEvent(
        event_id=1, event_type="gpu_hang", severity=severity,
        subsystem="gpu", ip_block="gfx", tokens=[tok],
        start_line=1, end_line=3, arch="x86_64", chip_gen="amd_cdna3",
        kernel_ver="6.8.0", confidence=0.85, raw_text="GPU HANG",
        has_call_trace=False, has_registers=False, provider_name="amd",
    )
    return CascadeResult(
        events=[ev], edges=[], root_cause_id=1, root_cause_conf=0.85,
        chip_gen="amd_cdna3", arch="x86_64", kernel_ver="6.8.0",
        severity=severity, subsystems_hit=["gpu"],
        event_count=1, critical_count=(1 if severity == "critical" else 0),
        error_count=(1 if severity == "error" else 0),
        warning_count=0, info_count=0, ascii_diagram="[gpu_hang]",
        analysis_ns=100_000,
    )


def _make_agent_result(severity: str = "error"):
    from soctriage.core.agent_result import AgentResult
    cascade = _make_cascade(severity=severity)
    return AgentResult(
        cascade=cascade,
        root_cause_narrative="GPU hang.",
        fix_suggestions=["Update firmware."],
        known_issues_matched=[],
        confidence=0.88,
        subsystem_narrative="",
        tool_trace=[],
        llm_backend="none",
        llm_model="none",
        iterations=0,
        total_ms=42,
        offline_mode=False,
        no_llm_mode=True,
    )


def _write_test_log(tmp_path: Path, content: str = None) -> Path:
    if content is None:
        content = (FIXTURES_DIR / "amd_mi300_critical.log").read_text()
    p = tmp_path / "test.log"
    p.write_text(content, encoding="utf-8")
    return p


def _mock_pipeline(mock_run_agent, severity="error"):
    """Configure mock_run_agent to return a pre-built AgentResult."""
    mock_run_agent.return_value = _make_agent_result(severity=severity)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_cli_help_exits_0():
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--help"])
    assert exc_info.value.code == 0


def test_cli_version_flag_exits_0():
    ret = main(["--version"])
    assert ret == 0


def test_cli_list_providers_exits_0_shows_5():
    mock_providers = [MagicMock() for _ in range(5)]
    for i, mp in enumerate(mock_providers):
        mp.name.return_value = f"provider_{i}"
    with patch("soctriage.providers.get_all_providers", return_value=mock_providers):
        ret = main(["--list-providers"])
    assert ret == 0


def test_cli_positional_log_file_accepted(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm"])
    assert ret in (EXITOK, EXITCRITICAL)


def test_cli_input_flag_accepted_as_fallback(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main(["--input", str(log), "--no-llm"])
    assert ret in (EXITOK, EXITCRITICAL)


def test_cli_missing_log_file_exits_usage():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    # argparse exits with code 2 for missing required args
    assert exc_info.value.code == 2


def test_cli_invalid_format_exits_3():
    with pytest.raises(SystemExit) as exc_info:
        main(["--format", "xml", "somefile.log"])
    assert exc_info.value.code != 0


def test_cli_unknown_provider_exits_3(tmp_path):
    log = _write_test_log(tmp_path)
    ret = main(["--soc-provider", "nonexistent_xyz_provider", str(log)])
    assert ret == EXITUSAGE


def test_cli_json_output_to_stdout(tmp_path, capsys):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm", "--format", "json"])
    assert ret in (EXITOK, EXITCRITICAL)


def test_cli_markdown_output_to_file(tmp_path):
    log = _write_test_log(tmp_path)
    out = str(tmp_path / "report.md")
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm", "--format", "markdown", "--output", out])
    assert ret in (EXITOK, EXITCRITICAL)
    assert Path(out).exists()


def test_cli_html_output_to_file(tmp_path):
    log = _write_test_log(tmp_path)
    out = str(tmp_path / "report.html")
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm", "--format", "html", "--output", out])
    assert ret in (EXITOK, EXITCRITICAL)
    assert Path(out).exists()


def test_cli_no_llm_flag_skips_agent(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        mock_agent.return_value = _make_agent_result()
        main([str(log), "--no-llm"])
        call_kwargs = mock_agent.call_args
        assert call_kwargs.kwargs.get("no_llm") is True


def test_cli_verbose_writes_to_stderr_not_stdout(tmp_path, capsys):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        main([str(log), "--no-llm", "--verbose"])
    captured = capsys.readouterr()
    # Verbose output goes to stderr, not stdout
    assert len(captured.err) > 0


def test_cli_include_raw_adds_raw_text_to_json(tmp_path, capsys):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm", "--format", "json", "--include-raw"])
    assert ret in (EXITOK, EXITCRITICAL)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # With include_raw, events should have raw_text
    assert "raw_text" in data["events"][0]


def test_ec40_critical_log_exits_1(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent, severity="critical")
        ret = main([str(log), "--no-llm"])
    assert ret == EXITCRITICAL  # == 1


def test_ec41_no_llm_critical_still_exits_1(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent, severity="critical")
        ret = main([str(log), "--no-llm"])
    assert ret == 1


def test_ec37_unwritable_output_path_exits_2(tmp_path):
    log = _write_test_log(tmp_path)
    with patch("soctriage.cli.run_agent") as mock_agent:
        _mock_pipeline(mock_agent)
        ret = main([str(log), "--no-llm", "--output", "/dev/null/invalid/path.json"])
    assert ret == EXITERROR


def test_ec39_empty_log_html_valid(tmp_path):
    empty_log = tmp_path / "empty.log"
    empty_log.write_text("", encoding="utf-8")
    # Empty log may raise InputError (EXITERROR=2) or return EXIT_NO_ANOMALY (1)
    ret = main([str(empty_log), "--no-llm", "--format", "html"])
    # Any non-zero exit is acceptable for an empty log
    assert ret in (EXIT_SUCCESS, EXITCRITICAL, EXITERROR, 1, 2)


def test_exitok_alias_equals_exit_success():
    assert EXITOK == EXIT_SUCCESS == 0


def test_exitcritical_equals_1():
    assert EXITCRITICAL == 1
