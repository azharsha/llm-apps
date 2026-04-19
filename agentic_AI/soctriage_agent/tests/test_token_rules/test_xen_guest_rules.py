"""test_xen_guest_rules.py — Phase 2d: xen_guest.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/xen_guest.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_xen_crash():       assert _r().match("xen:offline: VCPU panic", _ctx()) == "xen_crash"
def test_xen_grant_fail():  assert _r().match("xen-gntdev: grant map failed", _ctx()) == "xen_grant_fail"
def test_xen_event():       assert _r().match("xen_netfront: device initialised", _ctx()) == "xen_event"
