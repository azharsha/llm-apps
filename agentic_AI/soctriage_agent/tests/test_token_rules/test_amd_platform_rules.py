"""test_amd_platform_rules.py — Phase 2d: amd_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/amd_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_amd_smu_fail():        assert _r().match("amd-smu: smu init failed", _ctx()) == "amd_smu_fail"
def test_amd_psp_fail():        assert _r().match("amd-psp: command timeout", _ctx()) == "amd_psp_fail"
def test_amd_platform_event():  assert _r().match("k10temp: temperature reading", _ctx()) == "amd_platform_event"
