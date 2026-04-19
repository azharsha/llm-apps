"""test_drm_bridge_rules.py — Phase 2d: drm_bridge.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/drm_bridge.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_drm_bridge_fail():     assert _r().match("drm_bridge: attach failed", _ctx()) == "drm_bridge_fail"
def test_drm_connector_fail():  assert _r().match("drm: connector probe failed", _ctx()) == "drm_connector_fail"
def test_drm_bridge_event():    assert _r().match("drm: bridge reset complete", _ctx()) == "drm_bridge_event"
