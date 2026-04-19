"""test_opp_devfreq_rules.py — Phase 2c: opp_devfreq.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/opp_devfreq.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_freq_limit_hit():    assert _r().match("devfreq: max freq capped to 1GHz", _ctx()) == "freq_limit_hit"
def test_devfreq_event():     assert _r().match("devfreq: failed to set target frequency", _ctx()) == "devfreq_event"
def test_opp_event():         assert _r().match("opp: add failed for 800MHz", _ctx()) == "opp_event"
def test_opp_table_fail():    assert _r().match("_opp_table: not found for device", _ctx()) == "opp_event"
