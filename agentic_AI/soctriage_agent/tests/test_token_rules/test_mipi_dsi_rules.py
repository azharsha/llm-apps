"""test_mipi_dsi_rules.py — Phase 2d: mipi_dsi.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/mipi_dsi.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_dsi_panel_fail():  assert _r().match("mipi-dsi: panel init failed", _ctx()) == "dsi_panel_fail"
def test_dsi_phy_fail():    assert _r().match("dsi-phy: PLL lock failed", _ctx()) == "dsi_phy_fail"
def test_dsi_event():       assert _r().match("mipi_dsi: mode set complete", _ctx()) == "dsi_event"
