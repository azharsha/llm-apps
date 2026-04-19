"""test_nvdimm_pmem_rules.py — Phase 2c: nvdimm_pmem.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/nvdimm_pmem.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_nvdimm_event():    assert _r().match("nvdimm: device health degraded", _ctx()) == "nvdimm_event"
def test_pmem_event():      assert _r().match("pmem error on persistent memory region", _ctx()) == "pmem_event"
def test_dax_event():       assert _r().match("dax: failed to map region", _ctx()) == "dax_event"
def test_nvdimm_beats_pmem(): assert _r().match("nvdimm: pmem region error", _ctx()) == "nvdimm_event"
