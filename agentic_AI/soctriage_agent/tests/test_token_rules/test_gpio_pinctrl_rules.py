"""test_gpio_pinctrl_rules.py — Phase 2b: gpio_pinctrl.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/gpio_pinctrl.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_pinmux_conflict():    assert _r().match("pin already requested by spi0", _ctx()) == "pinmux_conflict"
def test_pinctrl_event():      assert _r().match("pinctrl: failed to select state", _ctx()) == "pinctrl_event"
def test_gpio_event():         assert _r().match("GPIO request failed for GPIO 42", _ctx()) == "gpio_event"
def test_conflict_beats_pinctrl():
    assert _r().match("pin conflict: pinmux conflict", _ctx()) == "pinmux_conflict"
