"""test_usb_rules.py — Phase 2b: usb.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/usb.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_usb_event():              assert _r().match("usb 1-1: USB disconnect, device number 2", _ctx()) == "usb_event"
def test_thunderbolt_event():      assert _r().match("thunderbolt 0-0: USB4 device detected", _ctx()) == "thunderbolt_event"
def test_thunderbolt_beats_usb():
    # thunderbolt (110) > usb (85)
    assert _r().match("thunderbolt: USB4 port error", _ctx()) == "thunderbolt_event"
