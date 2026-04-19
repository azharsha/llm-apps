"""test_ebpf_rules.py — Phase 2c: ebpf.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/ebpf.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_bpf_verifier_fail():   assert _r().match("BPF program rejected: invalid insn", _ctx()) == "bpf_verifier_fail"
def test_bpf_jit_fail():        assert _r().match("BPF JIT compilation failed", _ctx()) == "bpf_jit_fail"
def test_bpf_event():           assert _r().match("bpf: prog attached to cgroup", _ctx()) == "bpf_event"
def test_verifier_beats_jit():  assert _r().match("bpf verifier: BPF JIT too complex", _ctx()) == "bpf_verifier_fail"
