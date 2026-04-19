"""test_cxl_rules.py — Phase 2c: cxl.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/cxl.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_cxl_event():       assert _r().match("cxl_mem: device attached", _ctx()) == "cxl_event"
def test_cxl_mem_error():   assert _r().match("CXL: memory error on device 0", _ctx()) == "cxl_mem_error"
def test_cxl_link_fail():   assert _r().match("cxl_pci: fatal error on link", _ctx()) == "cxl_link_fail"
def test_mem_error_beats_event(): assert _r().match("cxl: uncorrectable error", _ctx()) == "cxl_mem_error"
