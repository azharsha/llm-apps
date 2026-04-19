"""test_rpi_platform_rules.py — Phase 2d: rpi_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/rpi_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "arm64", "unknown", [], [])

def test_rpi_firmware_fail():  assert _r().match("raspberrypi-firmware: property transaction failed", _ctx()) == "rpi_firmware_fail"
def test_rpi_mbox_fail():      assert _r().match("bcm2835-mbox: failed", _ctx()) == "rpi_mbox_fail"
def test_rpi_platform_event(): assert _r().match("bcm2835_clk: rate change", _ctx()) == "rpi_platform_event"
