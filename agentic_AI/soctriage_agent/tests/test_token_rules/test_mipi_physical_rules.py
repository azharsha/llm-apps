"""test_mipi_physical_rules.py — Phase 2d: mipi_physical.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/mipi_physical.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_mipi_phy_fail():   assert _r().match("mipi-cphy: PLL failed", _ctx()) == "mipi_phy_fail"
def test_mipi_phy_event():  assert _r().match("dphy: lane calibration done", _ctx()) == "mipi_phy_event"
