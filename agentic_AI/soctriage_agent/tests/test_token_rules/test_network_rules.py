"""test_network_rules.py — Phase 2c: network.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/network.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_network_event():      assert _r().match("net: device eth0 unregistered", _ctx()) == "network_event"
def test_roce_event():         assert _r().match("RoCE: connection refused", _ctx()) == "roce_event"
def test_infiniband_event():   assert _r().match("mlx5: device error", _ctx()) == "infiniband_event"
def test_ib_beats_roce():      assert _r().match("mlx5: RoCE event", _ctx()) == "infiniband_event"
