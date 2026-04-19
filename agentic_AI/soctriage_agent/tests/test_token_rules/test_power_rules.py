"""test_power_rules.py — Phase 2b: power.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/power.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_thermal_event():     assert _r().match("thermal_zone0: trip point 1 tripped", _ctx()) == "thermal_event"
def test_thermal_shutdown():  assert _r().match("thermal: thermal_emergency: shutdown", _ctx()) == "thermal_event"
def test_voltage_event():     assert _r().match("regulator: failed to get voltage", _ctx()) == "voltage_event"
def test_clk_event():         assert _r().match("clk: failed to enable clk_spi_core", _ctx()) == "clk_event"
def test_power_event():       assert _r().match("PM: suspend entry (deep)", _ctx()) == "power_event"
