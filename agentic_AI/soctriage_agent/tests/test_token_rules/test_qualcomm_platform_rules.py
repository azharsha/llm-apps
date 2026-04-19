"""test_qualcomm_platform_rules.py — Phase 2d: qualcomm_platform.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/qualcomm_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_qcom_subsys_crash():    assert _r().match("subsys: modem crashed", _ctx()) == "qcom_subsys_crash"
def test_qcom_smem_fail():       assert _r().match("qcom-smem: alloc failed", _ctx()) == "qcom_smem_fail"
def test_qcom_smd_fail():        assert _r().match("qcom-smd: open failed", _ctx()) == "qcom_smd_fail"
def test_qcom_platform_event():  assert _r().match("msm_bus: bandwidth vote applied", _ctx()) == "qcom_platform_event"
