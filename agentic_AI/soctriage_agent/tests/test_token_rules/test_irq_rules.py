"""test_irq_rules.py — Phase 2b: irq.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/irq.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_spinlock_fault():      assert _r().match("BUG: spinlock lockup on CPU#1", _ctx()) == "spinlock_fault"
def test_workqueue_stall():     assert _r().match("workqueue lockup detected", _ctx()) == "workqueue_stall"
def test_concurrency_fault():   assert _r().match("KCSAN: data race in foo+0x10", _ctx()) == "concurrency_fault"
def test_spinlock_beats_workqueue():
    assert _r().match("BUG: spinlock already unlocked", _ctx()) == "spinlock_fault"
