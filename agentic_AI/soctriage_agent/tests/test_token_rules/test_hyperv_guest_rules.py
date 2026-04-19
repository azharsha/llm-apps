"""test_hyperv_guest_rules.py — Phase 2d: hyperv_guest.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/hyperv_guest.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_hyperv_crash():       assert _r().match("hv_vmbus: failed to connect", _ctx()) == "hyperv_crash"
def test_hyperv_netvsc_fail(): assert _r().match("hv_netvsc: send buffer init failed", _ctx()) == "hyperv_netvsc_fail"
def test_hyperv_event():       assert _r().match("hv_storvsc: device connected", _ctx()) == "hyperv_event"
