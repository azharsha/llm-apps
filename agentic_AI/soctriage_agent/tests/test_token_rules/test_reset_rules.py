"""test_reset_rules.py — Phase 2b: reset.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/reset.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_reset_assert_fail():     assert _r().match("failed to assert reset for ufs", _ctx()) == "reset_assert_fail"
def test_reset_deassert_fail():   assert _r().match("failed to deassert reset for usb", _ctx()) == "reset_deassert_fail"
def test_reset_ctrl_event():      assert _r().match("deassert reset for block pcie", _ctx()) == "reset_ctrl_event"
def test_reset_timeout():         assert _r().match("reset: timeout on deassert", _ctx()) == "reset_deassert_fail"
