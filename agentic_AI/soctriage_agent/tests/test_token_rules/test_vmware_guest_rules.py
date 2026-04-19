"""test_vmware_guest_rules.py — Phase 2d: vmware_guest.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/vmware_guest.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_vmware_tools_fail():  assert _r().match("vmw_vmci: failed", _ctx()) == "vmware_tools_fail"
def test_vmware_pvscsi_fail(): assert _r().match("pvscsi: reset bus", _ctx()) == "vmware_pvscsi_fail"
def test_vmware_event():       assert _r().match("vmxnet3: adapter reset", _ctx()) == "vmware_event"
