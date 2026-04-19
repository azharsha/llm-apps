"""test_regmap_rules.py — Phase 2d: regmap.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/regmap.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_regmap_error():  assert _r().match("regmap: error", _ctx()) == "regmap_error"
def test_regmap_event():  assert _r().match("regmap-i2c: cache synced", _ctx()) == "regmap_event"
