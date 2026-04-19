"""test_input_hid_rules.py — Phase 2d: input_hid.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/input_hid.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_hid_error():    assert _r().match("hid-core: failed to claim input", _ctx()) == "hid_error"
def test_input_event():  assert _r().match("input: keyboard registered", _ctx()) == "input_event"
