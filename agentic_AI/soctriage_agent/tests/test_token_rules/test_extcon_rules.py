"""test_extcon_rules.py — Phase 2d: extcon.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/extcon.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_extcon_error():  assert _r().match("extcon: registration failed", _ctx()) == "extcon_error"
def test_extcon_event():  assert _r().match("extcon_gpio: state changed", _ctx()) == "extcon_event"
