"""test_storage_rules.py — Phase 2b: storage.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/storage.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_ufs_event():      assert _r().match("ufshcd: error -110 in power management", _ctx()) == "ufs_event"
def test_emmc_event():     assert _r().match("mmc0: error -110 whilst initialising", _ctx()) == "emmc_event"
def test_nvme_event():     assert _r().match("nvme nvme0: controller is down", _ctx()) == "nvme_event"
def test_io_error():       assert _r().match("I/O error on device sda", _ctx()) == "io_error"
def test_nvme_beats_io():
    # nvme (110) > io_error (75): NVMe I/O error should match nvme
    assert _r().match("nvme nvme0: I/O error", _ctx()) == "nvme_event"
