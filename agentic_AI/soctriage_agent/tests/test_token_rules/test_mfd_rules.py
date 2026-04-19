"""test_mfd_rules.py — Phase 2c: mfd.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/mfd.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_mfd_child_fail():   assert _r().match("mfd: failed to add device pm8150", _ctx()) == "mfd_child_fail"
def test_pmic_event():       assert _r().match("PMIC irq triggered on line 42", _ctx()) == "pmic_event"
def test_mfd_event():        assert _r().match("mfd: device registered", _ctx()) == "mfd_event"
def test_pmic_beats_mfd():   assert _r().match("pmic: mfd event triggered", _ctx()) == "pmic_event"
