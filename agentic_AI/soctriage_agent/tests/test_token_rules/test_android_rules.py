"""test_android_rules.py — Phase 2c: android.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/android.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_android_panic_sigsegv():  assert _r().match("Fatal signal 11 (SIGSEGV) at 0x00000000", _ctx()) == "android_panic"
def test_android_panic_tombstone(): assert _r().match("tombstone written: /data/tombstones/tombstone_01", _ctx()) == "android_panic"
def test_binder_event():           assert _r().match("binder: transaction failed -22", _ctx()) == "binder_event"
def test_ion_event():              assert _r().match("ion: ION: allocation failed for 1048576 bytes", _ctx()) == "ion_event"
def test_android_panic_beats_binder(): assert _r().match("binder: Fatal signal 9", _ctx()) == "android_panic"
