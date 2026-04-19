"""test_edac_rules.py — Phase 2d: edac.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/edac.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_edac_ue():     assert _r().match("EDAC MC: uncorrected error", _ctx()) == "edac_ue"
def test_edac_ce():     assert _r().match("EDAC MC: corrected error", _ctx()) == "edac_ce"
def test_edac_event():  assert _r().match("edac_mc: polling complete", _ctx()) == "edac_event"
