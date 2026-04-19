"""test_media_isp_rules.py — Phase 2d: media_isp.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/media_isp.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_isp_crash():     assert _r().match("isp: fatal error", _ctx()) == "isp_crash"
def test_camera_fail():   assert _r().match("camera: sensor probe failed", _ctx()) == "camera_fail"
def test_isp_event():     assert _r().match("cam_isp: enabling pipeline", _ctx()) == "isp_event"
