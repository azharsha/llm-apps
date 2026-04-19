"""test_mediatek_platform_rules.py — Phase 2d: mediatek_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/mediatek_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_mtk_scp_fail():         assert _r().match("mtk-scp: firmware load failed", _ctx()) == "mtk_scp_fail"
def test_mtk_mmsys_fail():       assert _r().match("mediatek-mmsys: power on failed", _ctx()) == "mtk_mmsys_fail"
def test_mtk_platform_event():   assert _r().match("mtk_thermal: throttling started", _ctx()) == "mtk_platform_event"
