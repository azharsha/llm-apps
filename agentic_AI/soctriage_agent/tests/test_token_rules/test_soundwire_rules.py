"""test_soundwire_rules.py — Phase 2d: soundwire.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/soundwire.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_soundwire_error():  assert _r().match("soundwire: sync failed", _ctx()) == "soundwire_error"
def test_soundwire_event():  assert _r().match("intel-sdw: device ready", _ctx()) == "soundwire_event"
