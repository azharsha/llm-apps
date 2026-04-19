"""test_wifi_rules.py — Phase 2d: wifi.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/wifi.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_wifi_fw_crash():     assert _r().match("ath10k: firmware crashed", _ctx()) == "wifi_fw_crash"
def test_wifi_auth_fail():    assert _r().match("wlan: authentication failed", _ctx()) == "wifi_auth_fail"
def test_wifi_scan_fail():    assert _r().match("cfg80211: scan failed", _ctx()) == "wifi_scan_fail"
def test_wifi_disconnect():   assert _r().match("wlan: disconnected", _ctx()) == "wifi_disconnect"
def test_wifi_event():        assert _r().match("mac80211: adding interface", _ctx()) == "wifi_event"
