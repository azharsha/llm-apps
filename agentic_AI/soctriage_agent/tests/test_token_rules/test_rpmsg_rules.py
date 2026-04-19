"""test_rpmsg_rules.py — Phase 2b: rpmsg.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/rpmsg.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_rpmsg_ipc_error():      assert _r().match("rpmsg: timeout waiting for response", _ctx()) == "rpmsg_ipc_error"
def test_rpmsg_channel_fail():   assert _r().match("rpmsg: channel creation failed for ept", _ctx()) == "rpmsg_channel_fail"
def test_rpmsg_event():          assert _r().match("rpmsg_core: endpoint registered", _ctx()) == "rpmsg_event"
def test_glink_event():          assert _r().match("glink: ch open failed", _ctx()) == "rpmsg_channel_fail"
