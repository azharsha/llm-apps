"""test_remoteproc_rules.py — Phase 2b: remoteproc.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/remoteproc.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_remoteproc_crash():     assert _r().match("remoteproc: crash detected on modem", _ctx()) == "remoteproc_crash"
def test_remoteproc_fw_fail():   assert _r().match("remoteproc: failed to load modem.mbn", _ctx()) == "remoteproc_fw_fail"
def test_remoteproc_event():     assert _r().match("rproc: firmware not available for cdsp", _ctx()) == "remoteproc_fw_fail"
def test_rproc_crash():          assert _r().match("rproc: crash on cdsp processor", _ctx()) == "remoteproc_crash"
