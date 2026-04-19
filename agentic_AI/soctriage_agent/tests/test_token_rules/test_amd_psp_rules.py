"""test_amd_psp_rules.py — Phase 2d: amd_psp.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/amd_psp.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "x86_64", "unknown", [], [])

def test_psp_fw_load_fail():  assert _r().match("amd-psp: failed to load firmware", _ctx()) == "psp_fw_load_fail"
def test_psp_ring_fail():     assert _r().match("psp: ring buffer error", _ctx()) == "psp_ring_fail"
def test_psp_tee_fail():      assert _r().match("psp: TEE init failed", _ctx()) == "psp_tee_fail"
def test_psp_event():         assert _r().match("psp: command submitted", _ctx()) == "psp_event"
