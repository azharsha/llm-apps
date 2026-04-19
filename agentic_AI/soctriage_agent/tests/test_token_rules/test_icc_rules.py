"""test_icc_rules.py — Phase 2d: icc.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/icc.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_icc_set_fail():  assert _r().match("icc: set failed", _ctx()) == "icc_set_fail"
def test_icc_event():     assert _r().match("qcom-icc: path registered", _ctx()) == "icc_event"
