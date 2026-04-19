"""test_memory_rules.py — Phase 2b: memory.yaml (8 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/memory.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_memory_event_kasan():      assert _r().match("KASAN: use-after-free in foo+0x4", _ctx()) in ("memory_event", "kasan_detail")
def test_memory_event_slub():       assert _r().match("SLUB: Unable to allocate memory", _ctx()) == "memory_event"
def test_kasan_detail_read():       assert _r().match("Read of size 8 at addr ffff0000 by", _ctx()) == "kasan_detail"
def test_memory_poison():           assert _r().match("Memory failure: 0x1234: Killing", _ctx()) == "memory_poison"
def test_hwpoison():                assert _r().match("HWPoison page at 0x12345678", _ctx()) == "memory_poison"
def test_oom_event():               assert _r().match("Out of memory: Killed process 1234", _ctx()) == "oom_event"
def test_refcount_fault():          assert _r().match("refcount_t: addition on 0", _ctx()) == "refcount_fault"
def test_memory_event_exclude_self_test():
    r = _r()
    assert r.match("KASAN: self-test passed", _ctx()) == "unknown"
