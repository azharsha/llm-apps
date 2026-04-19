"""test_kasan_detail_ext_rules.py — Phase 2d: kasan_detail_ext.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/kasan_detail_ext.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_kfence_error():      assert _r().match("KFENCE: use-after-free", _ctx()) == "kfence_error"
def test_kmsan_error():       assert _r().match("BUG: KMSAN: uninit-value", _ctx()) == "kmsan_error"
def test_kasan_heap_detail(): assert _r().match("KASAN: slab-out-of-bounds", _ctx()) == "kasan_heap_detail"
