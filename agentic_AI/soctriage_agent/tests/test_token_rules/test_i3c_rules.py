"""test_i3c_rules.py — Phase 2d: i3c.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/i3c.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_i3c_error():  assert _r().match("i3c: transfer error", _ctx()) == "i3c_error"
def test_i3c_event():  assert _r().match("i3c_master: bus initialized", _ctx()) == "i3c_event"
