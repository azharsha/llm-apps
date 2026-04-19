"""test_fs_block_rules.py — Phase 2c: fs_block.yaml (6 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/fs_block.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_btrfs_event():    assert _r().match("BTRFS: error on device sda1", _ctx()) == "btrfs_event"
def test_xfs_event():      assert _r().match("XFS: metadata corruption detected", _ctx()) == "xfs_event"
def test_ext4_event():     assert _r().match("EXT4-fs error (device sda2)", _ctx()) == "ext4_event"
def test_dm_event():       assert _r().match("device-mapper: table reload failed", _ctx()) == "dm_event"
def test_blk_mq_event():   assert _r().match("blk_mq: request timeout on queue 0", _ctx()) == "blk_mq_event"
def test_btrfs_beats_xfs():
    assert _r().match("BTRFS: XFS-style metadata write", _ctx()) == "btrfs_event"
