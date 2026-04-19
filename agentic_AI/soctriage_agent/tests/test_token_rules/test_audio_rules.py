"""test_audio_rules.py — Phase 2c: audio.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/audio.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_audio_dsp_fail():   assert _r().match("audio dsp failed to boot", _ctx()) == "audio_dsp_fail"
def test_asoc_event():       assert _r().match("ASoC: no backend DAIs enabled for codec", _ctx()) == "asoc_event"
def test_codec_event():      assert _r().match("audio codec error on I2C", _ctx()) == "codec_event"
def test_dsp_beats_asoc():   assert _r().match("ASoC: audio firmware timeout", _ctx()) == "audio_dsp_fail"
