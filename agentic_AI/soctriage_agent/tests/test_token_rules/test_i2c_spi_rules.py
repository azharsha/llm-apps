"""test_i2c_spi_rules.py — Phase 2c: i2c_spi.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/i2c_spi.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_i2c_nack():       assert _r().match("I2C NACK from device 0x52", _ctx()) == "i2c_nack"
def test_spi_timeout():    assert _r().match("spi: timeout waiting for transfer", _ctx()) == "spi_timeout"
def test_i2c_event():      assert _r().match("i2c-core: adapter registered", _ctx()) == "i2c_event"
def test_spi_event():      assert _r().match("spi-nor: flash detected", _ctx()) == "spi_event"
def test_i2c_nack_beats_event(): assert _r().match("i2c: nack on address 0x52", _ctx()) == "i2c_nack"
