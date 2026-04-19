"""test_perf_pmu_rules.py — Phase 2c: perf_pmu.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/perf_pmu.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_uncore_event():    assert _r().match("uncore_pmu: device registered", _ctx()) == "uncore_event"
def test_pmu_event():       assert _r().match("PMU: hardware counter overflow", _ctx()) == "pmu_event"
def test_perf_event():      assert _r().match("perf: interrupt took too long", _ctx()) == "perf_event"
def test_uncore_beats_pmu(): assert _r().match("uncore: PMU device init", _ctx()) == "uncore_event"
