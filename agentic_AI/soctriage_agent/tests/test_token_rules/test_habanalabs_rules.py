"""test_habanalabs_rules.py — Phase 2d: habanalabs.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/habanalabs.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_habana_crash():     assert _r().match("habanalabs: device reset", _ctx()) == "habana_crash"
def test_habana_fw_fail():   assert _r().match("habanalabs: firmware load failed", _ctx()) == "habana_fw_fail"
def test_habana_event():     assert _r().match("hl_device: ready", _ctx()) == "habana_event"
