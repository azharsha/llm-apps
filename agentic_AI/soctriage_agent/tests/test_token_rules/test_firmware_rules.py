"""test_firmware_rules.py — Phase 2b: firmware.yaml (7 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/firmware.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_bootloader_event():      assert _r().match("ABL: boot sequence complete", _ctx()) == "bootloader_event"
def test_secure_boot_event():     assert _r().match("Secure Boot violation detected", _ctx()) == "secure_boot_event"
def test_lockdown_event():        assert _r().match("Lockdown: hibernation: is restricted", _ctx()) == "secure_boot_event"
def test_tee_event():             assert _r().match("SMC call failed with error -22", _ctx()) == "tee_event"
def test_firmware_event_guc():    assert _r().match("GuC firmware load failed", _ctx()) == "firmware_event"
def test_module_event():          assert _r().match("FATAL: Module mymod not found", _ctx()) == "module_event"
def test_initrd_event():          assert _r().match("unpacking initramfs...", _ctx()) == "initrd_event"
