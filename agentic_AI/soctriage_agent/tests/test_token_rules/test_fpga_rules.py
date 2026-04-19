"""test_fpga_rules.py — Phase 2d: fpga.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/fpga.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_fpga_load_fail():  assert _r().match("fpga_manager: writing to FPGA failed", _ctx()) == "fpga_load_fail"
def test_fpga_event():      assert _r().match("fpga_bridge: enabled", _ctx()) == "fpga_event"
