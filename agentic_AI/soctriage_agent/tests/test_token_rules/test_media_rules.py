"""test_media_rules.py — Phase 2c: media.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/media.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_camera_fail():       assert _r().match("camera: failed to power on sensor", _ctx()) == "camera_fail"
def test_video_codec_fail():  assert _r().match("video codec failed to decode frame", _ctx()) == "video_codec_fail"
def test_isp_event():         assert _r().match("isp: timeout on pipeline flush", _ctx()) == "isp_event"
def test_v4l2_event():        assert _r().match("v4l2: video_device registered", _ctx()) == "v4l2_event"
def test_camera_beats_isp():  assert _r().match("isp: camera sensor not found", _ctx()) == "camera_fail"
