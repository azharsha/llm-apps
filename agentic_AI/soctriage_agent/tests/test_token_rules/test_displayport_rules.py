"""test_displayport_rules.py — Phase 2d: displayport.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/displayport.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_dp_link_fail():  assert _r().match("dp: link training failed", _ctx()) == "dp_link_fail"
def test_dp_hotplug():    assert _r().match("dp: hotplug detected", _ctx()) == "dp_hotplug"
def test_dp_event():      assert _r().match("drm_dp: aux transfer complete", _ctx()) == "dp_event"
