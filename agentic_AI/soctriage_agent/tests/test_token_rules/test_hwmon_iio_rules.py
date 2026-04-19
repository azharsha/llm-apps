"""test_hwmon_iio_rules.py — Phase 2c: hwmon_iio.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/hwmon_iio.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_thermal_sensor_fail():   assert _r().match("hwmon: sensor timeout on temp1", _ctx()) == "thermal_sensor_fail"
def test_hwmon_event():           assert _r().match("hwmon: device registered", _ctx()) == "hwmon_event"
def test_iio_event():             assert _r().match("iio: buffer flush timeout", _ctx()) == "iio_event"
def test_sensor_fail_beats_hwmon(): assert _r().match("hwmon: thermal sensor failure", _ctx()) == "thermal_sensor_fail"
