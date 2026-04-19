"""test_coresight_rules.py — Phase 2c: coresight.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/coresight.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(arch="any"): return TokenContext(1, arch, "unknown", [], [])

def test_etm_event():         assert _r().match("coresight-etm4x: ETM: enabled", _ctx(arch="arm64")) == "etm_event"
def test_etm_not_x86():       assert _r().match("etm: ETM enabled", _ctx(arch="x86_64")) != "etm_event"
def test_stm_event():         assert _r().match("STM: channel 0 registered", _ctx()) == "stm_event"
def test_coresight_event():   assert _r().match("coresight: sink registered", _ctx()) == "coresight_event"
