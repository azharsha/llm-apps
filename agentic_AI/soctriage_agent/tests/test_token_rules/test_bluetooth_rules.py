"""test_bluetooth_rules.py — Phase 2d: bluetooth.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/bluetooth.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_bt_fw_crash():       assert _r().match("hci0: command tx timeout", _ctx()) == "bt_fw_crash"
def test_bt_hci_error():      assert _r().match("hci_error: unexpected event", _ctx()) == "bt_hci_error"
def test_bt_connect_fail():   assert _r().match("Bluetooth: connection failed", _ctx()) == "bt_connect_fail"
def test_bt_event():          assert _r().match("btusb: device disconnected", _ctx()) == "bt_event"
