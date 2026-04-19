"""test_tty_uart_rules.py — Phase 2d: tty_uart.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/tty_uart.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_uart_error():  assert _r().match("serial: too much work for irq", _ctx()) == "uart_error"
def test_tty_event():   assert _r().match("8250: uart registered", _ctx()) == "tty_event"
