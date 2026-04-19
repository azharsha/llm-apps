"""test_namespace_rules.py — Phase 2c: namespace.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/namespace.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_seccomp_event():    assert _r().match("SECCOMP violation in pid 1234", _ctx()) == "seccomp_event"
def test_landlock_event():   assert _r().match("Landlock: access denied for /etc/passwd", _ctx()) == "landlock_event"
def test_ns_event():         assert _r().match("user_ns: uid map overflow", _ctx()) == "ns_event"
def test_seccomp_beats_ns(): assert _r().match("seccomp: namespace violation", _ctx()) == "seccomp_event"
