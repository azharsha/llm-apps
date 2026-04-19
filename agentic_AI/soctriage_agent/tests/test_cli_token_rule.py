"""
tests/test_cli_token_rule.py — Phase 2e: 5 CLI flag tests.
"""
from __future__ import annotations

import sys
import pytest
from pathlib import Path

from soctriage.cli import build_parser, _parse_inline_rule, EXIT_INPUT_ERR


def test_extra_rules_parsed_from_cli() -> None:
    args = build_parser().parse_args(["--token-rule", "cxl_event:cxl_mem:"])
    assert args.extra_rules == ["cxl_event:cxl_mem:"]


def test_multiple_token_rules_all_loaded() -> None:
    args = build_parser().parse_args([
        "--token-rule", "cxl_event:cxl_mem:",
        "--token-rule", "cxl_event:CXL: error",
        "--token-rule", "cxl_event:cxl_pci: fatal",
    ])
    assert len(args.extra_rules) == 3


def test_plugin_file_flag_parsed() -> None:
    args = build_parser().parse_args(["--plugin", "plugins/my_soc_rules.py"])
    assert args.plugin_files == ["plugins/my_soc_rules.py"]


def test_token_rule_no_colon_raises_usage_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_inline_rule("NOCOLON")
    assert exc_info.value.code == EXIT_INPUT_ERR


def test_token_rule_injected_correctly() -> None:
    rule = _parse_inline_rule("my_event:some pattern here")
    assert rule.token_type == "my_event"
    assert rule.patterns == ["some pattern here"]
    assert rule.priority == 190
    assert rule.match_mode == "any"
