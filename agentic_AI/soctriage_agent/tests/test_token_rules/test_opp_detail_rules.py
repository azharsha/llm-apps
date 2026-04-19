"""test_opp_detail_rules.py — Phase 2d: opp_detail.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/opp_detail.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_opp_corner_fail():    assert _r().match("opp: corner voltage set failed", _ctx()) == "opp_corner_fail"
def test_opp_detail_event():   assert _r().match("cpr3-regulator: corner set", _ctx()) == "opp_detail_event"
