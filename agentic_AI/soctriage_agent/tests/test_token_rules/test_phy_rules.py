"""test_phy_rules.py — Phase 2b: phy.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/phy.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_phy_calibration_fail():  assert _r().match("PHY calibration failed for pcie0", _ctx()) == "phy_calibration_fail"
def test_phy_init_fail():         assert _r().match("PHY init failed with error -110", _ctx()) == "phy_init_fail"
def test_phy_event():             assert _r().match("PHY power on failed for usb3", _ctx()) == "phy_init_fail"
def test_serdes_cal_fail():       assert _r().match("SERDES cal failed on phy0", _ctx()) == "phy_calibration_fail"
