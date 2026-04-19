"""test_cpu_rules.py — Phase 2b: cpu.yaml (10 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/cpu.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(arch="any"):
    return TokenContext(1, arch, "unknown", [], [])

def test_cpu_hotplug():            assert _r().match("CPU 3: died", _ctx()) == "cpu_hotplug"
def test_cpu_idle_fail():          assert _r().match("cpuidle: failed to enter", _ctx()) == "cpu_idle_fail"
def test_preempt_fault():          assert _r().match("BUG: scheduling while atomic", _ctx()) == "preempt_fault"
def test_sched_stall():            assert _r().match("sched: RT throttling activated", _ctx()) == "sched_stall"
def test_simd_fault():             assert _r().match("trap: invalid opcode", _ctx()) == "simd_fault"
def test_oops_arm64_specific():    assert _r().match("Bad mode in User handler", _ctx(arch="arm64")) == "oops_arm64_specific"
def test_oops_arm64_not_x86():     assert _r().match("Bad mode in User handler", _ctx(arch="x86_64")) != "oops_arm64_specific"
def test_speculation_fault():      assert _r().match("Spectre v2: IBRS enabled", _ctx()) == "speculation_fault"
def test_priority_inversion():     assert _r().match("rtmutex: deadlock detected", _ctx()) == "priority_inversion"
def test_context_switch_fault():   assert _r().match("bad RSP value", _ctx()) == "context_switch_fault"
