"""test_nvidia_platform_rules.py — Phase 2d: nvidia_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/nvidia_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "arm64", "unknown", [], [])

def test_tegra_hsp_fail():      assert _r().match("tegra-hsp: doorbell timeout", _ctx()) == "tegra_hsp_fail"
def test_tegra_mc_fail():       assert _r().match("tegra-mc: fault", _ctx()) == "tegra_mc_fail"
def test_nvidia_platform_event(): assert _r().match("tegra_clk: rate change", _ctx()) == "nvidia_platform_event"
