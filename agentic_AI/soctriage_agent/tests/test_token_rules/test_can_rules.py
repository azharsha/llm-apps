"""test_can_rules.py — Phase 2d: can.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/can.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_can_bus_error():  assert _r().match("can: bus error", _ctx()) == "can_bus_error"
def test_can_event():      assert _r().match("flexcan: bitrate configured", _ctx()) == "can_event"
