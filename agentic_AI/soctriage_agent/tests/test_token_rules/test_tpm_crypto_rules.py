"""test_tpm_crypto_rules.py — Phase 2c: tpm_crypto.yaml (5 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/tpm_crypto.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_ima_event():        assert _r().match("ima: violation at /usr/bin/ssh", _ctx()) == "ima_event"
def test_tpm_event():        assert _r().match("tpm: tpm_tis timeout", _ctx()) == "tpm_event"
def test_keyring_event():    assert _r().match("key rejected: asymmetric key invalid", _ctx()) == "keyring_event"
def test_crypto_event():     assert _r().match("crypto: alg not found", _ctx()) == "crypto_event"
def test_ima_beats_tpm():    assert _r().match("tpm: IMA: measurement failed", _ctx()) == "ima_event"
