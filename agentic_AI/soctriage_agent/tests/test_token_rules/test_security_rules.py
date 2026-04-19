"""test_security_rules.py — Phase 2c: security.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/security.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_sanitizer_ubsan():       assert _r().match("UBSAN: array index out of bounds", _ctx()) == "sanitizer_event"
def test_sanitizer_excludes_kasan(): assert _r().match("KASAN: memory corruption", _ctx()) == "unknown"
def test_audit_event():           assert _r().match("audit: type=AVC msg=apparmor", _ctx()) == "audit_event"
def test_speculation_fault():     assert _r().match("MMIO Stale Data mitigation active", _ctx()) == "speculation_fault"
