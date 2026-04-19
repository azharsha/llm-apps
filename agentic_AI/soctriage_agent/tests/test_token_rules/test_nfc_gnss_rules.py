"""test_nfc_gnss_rules.py — Phase 2d: nfc_gnss.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/nfc_gnss.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_nfc_event():  assert _r().match("nfc: target found", _ctx()) == "nfc_event"
def test_gnss_event(): assert _r().match("gnss: fix acquired", _ctx()) == "gnss_event"
def test_uwb_event():  assert _r().match("uwb: ranging started", _ctx()) == "uwb_event"
