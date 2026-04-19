"""test_slimbus_rules.py — Phase 2d: slimbus.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/slimbus.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_slimbus_error():  assert _r().match("slim: enumeration failed", _ctx()) == "slimbus_error"
def test_slimbus_event():  assert _r().match("qcom-slim: device registered", _ctx()) == "slimbus_event"
