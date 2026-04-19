"""test_rtc_rules.py — Phase 2d: rtc.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/rtc.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_rtc_error():  assert _r().match("rtc: unable to set time", _ctx()) == "rtc_error"
def test_rtc_event():  assert _r().match("rtc0: time set complete", _ctx()) == "rtc_event"
