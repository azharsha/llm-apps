"""test_debug_infra_rules.py — Phase 2c: debug_infra.yaml (8 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/debug_infra.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_ramoops_event():        assert _r().match("ramoops: found existing crashlog", _ctx()) == "ramoops_event"
def test_pstore_event():         assert _r().match("pstore: backend registered", _ctx()) == "ramoops_event"
def test_ras_event():            assert _r().match("RAS: memory error detected", _ctx()) == "ras_event"
def test_edac_mc():              assert _r().match("EDAC MC: correctable error", _ctx()) == "ras_event"
def test_kgdb_event():           assert _r().match("KGDB: waiting for connection", _ctx()) == "kgdb_event"
def test_ftrace_event():         assert _r().match("ftrace: allocated 512k pages", _ctx()) == "ftrace_event"
def test_kunit_event():          assert _r().match("KUNIT FAILED: test_alloc_buffer", _ctx()) == "kunit_event"
def test_ramoops_beats_ras():
    r = _r()
    # ramoops (160) > ras (130)
    assert r.match("ramoops: RAS: event found in pstore", _ctx()) == "ramoops_event"
