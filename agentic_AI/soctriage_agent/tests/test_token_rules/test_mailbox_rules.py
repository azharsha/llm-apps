"""test_mailbox_rules.py — Phase 2d: mailbox.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/mailbox.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_mailbox_error():  assert _r().match("mailbox: channel busy timeout", _ctx()) == "mailbox_error"
def test_mailbox_event():  assert _r().match("qcom-ipcc: channel ready", _ctx()) == "mailbox_event"
