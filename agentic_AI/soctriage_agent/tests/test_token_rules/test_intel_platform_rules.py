"""test_intel_platform_rules.py — Phase 2d: intel_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/intel_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_intel_me_fail():        assert _r().match("mei_me: hw reset failed", _ctx()) == "intel_me_fail"
def test_intel_punit_fail():     assert _r().match("intel_punit: error", _ctx()) == "intel_punit_fail"
def test_intel_platform_event(): assert _r().match("pch_thermal: critical temp", _ctx()) == "intel_platform_event"
