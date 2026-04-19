"""test_spmi_rules.py — Phase 2b: spmi.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/spmi.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(arch="arm64"):
    return TokenContext(1, arch, "unknown", [], [])

def test_spmi_bus_error():    assert _r().match("SPMI transaction failed on bus 0", _ctx()) == "spmi_bus_error"
def test_spmi_pmic_event():   assert _r().match("pm8998: PMIC interrupt", _ctx()) == "spmi_pmic_event"
def test_spmi_event():        assert _r().match("spmi-pmic-arb: SPMI error", _ctx()) == "spmi_event"
def test_spmi_bus_beats_event(): assert _r().match("SPMI timeout on bus 0", _ctx()) == "spmi_bus_error"
