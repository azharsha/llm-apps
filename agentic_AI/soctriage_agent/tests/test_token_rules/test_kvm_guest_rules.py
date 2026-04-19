"""test_kvm_guest_rules.py — Phase 2d: kvm_guest.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/kvm_guest.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_kvm_mmu_fail():   assert _r().match("kvm: mmu page fault unhandled", _ctx()) == "kvm_mmu_fail"
def test_kvm_vcpu_fail():  assert _r().match("kvm: VCPU run failed", _ctx()) == "kvm_vcpu_fail"
def test_kvm_event():      assert _r().match("virtio_blk: device registered", _ctx()) == "kvm_event"
