"""test_concurrency_rules.py — Phase 2c: concurrency.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/concurrency.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_priority_inversion():      assert _r().match("PI-futex: owner died waiting", _ctx()) == "priority_inversion"
def test_context_switch_fault():    assert _r().match("preempt count underflow: pid 1234", _ctx()) == "context_switch_fault"
def test_pi_beats_context_switch(): assert _r().match("rtmutex: owner died", _ctx()) == "priority_inversion"
