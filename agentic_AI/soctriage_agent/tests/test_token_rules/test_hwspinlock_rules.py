"""test_hwspinlock_rules.py — Phase 2d: hwspinlock.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/hwspinlock.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_hwspinlock_error():  assert _r().match("hwspinlock: timeout", _ctx()) == "hwspinlock_error"
def test_hwspinlock_event():  assert _r().match("qcom-hwspinlock: lock acquired", _ctx()) == "hwspinlock_event"
