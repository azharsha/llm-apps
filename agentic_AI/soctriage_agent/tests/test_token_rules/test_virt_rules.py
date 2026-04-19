"""test_virt_rules.py — Phase 2c: virt.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/virt.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_vfio_event():       assert _r().match("vfio: device assignment failed", _ctx()) == "vfio_event"
def test_kvm_event():        assert _r().match("KVM: entry failed for vcpu 0", _ctx()) == "kvm_event"
def test_cgroup_event():     assert _r().match("cgroup out of memory: kill process", _ctx()) == "cgroup_event"
def test_vfio_beats_kvm():   assert _r().match("vfio_pci: iommu group error", _ctx()) == "vfio_event"
