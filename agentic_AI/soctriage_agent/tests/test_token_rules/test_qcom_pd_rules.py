"""test_qcom_pd_rules.py — Phase 2d: qcom_pd.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/qcom_pd.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_qcom_pd_crash():    assert _r().match("pd_mapper: remote pd crash", _ctx()) == "qcom_pd_crash"
def test_qcom_adsp_crash():  assert _r().match("adsp: subsystem crash", _ctx()) == "qcom_adsp_crash"
def test_qcom_cdsp_crash():  assert _r().match("cdsp: subsystem crash", _ctx()) == "qcom_cdsp_crash"
def test_qcom_slpi_crash():  assert _r().match("slpi: subsystem crash", _ctx()) == "qcom_slpi_crash"
def test_qcom_pd_event():    assert _r().match("qcom_pd: state changed", _ctx()) == "qcom_pd_event"
