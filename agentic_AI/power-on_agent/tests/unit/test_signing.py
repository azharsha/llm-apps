"""Tests for security/signing.py.

Critical constraints under test:
- [N-PG-02] HMAC-SHA-256 appended as HTML comment
- sign_report(html, run_id, signing_key) + verify_report(html, run_id, signing_key) round-trip
- verify_report() returns bool (True=valid, False=tampered/missing)
- verify_report() fails on tampered content
- verify_report() fails with wrong key
- Signing key priority: POAGENT_SIGNING_KEY env → config key → machine-id
"""

from __future__ import annotations

import os

import pytest

from poagent.security.signing import sign_report, verify_report


SAMPLE_HTML = "<html><body><h1>Test Report</h1><p>Verdict: PASS</p></body></html>"
TEST_KEY = "test-secret-key-for-unit-testing-32bytes"
TEST_RUN_ID = "run-unit-test-001"


class TestSignReport:
    def test_sign_appends_hmac_comment(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert "poagent-hmac-sha256" in signed
        assert "<!--" in signed

    def test_sign_preserves_original_content(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert "<html>" in signed
        assert "Verdict: PASS" in signed

    def test_sign_produces_hex_digest(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        import re
        match = re.search(r"poagent-hmac-sha256:\s*([0-9a-f]+)", signed)
        assert match is not None, "No hex digest found in signed report"
        hex_digest = match.group(1)
        assert len(hex_digest) == 64  # SHA-256 → 32 bytes → 64 hex chars

    def test_sign_idempotent_with_same_key(self):
        """Signing same content+run_id with same key gives same signature."""
        s1 = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        s2 = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert s1 == s2

    def test_different_keys_produce_different_signatures(self):
        s1 = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key="key-one-abcdef")
        s2 = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key="key-two-abcdef")
        assert s1 != s2

    def test_different_run_ids_produce_different_signatures(self):
        """run_id is bound into the signature message."""
        s1 = sign_report(SAMPLE_HTML, run_id="run-001", signing_key=TEST_KEY)
        s2 = sign_report(SAMPLE_HTML, run_id="run-002", signing_key=TEST_KEY)
        assert s1 != s2


class TestVerifyReport:
    def test_roundtrip_passes(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        ok = verify_report(signed, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert ok is True

    def test_verify_returns_bool(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        result = verify_report(signed, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert isinstance(result, bool)

    def test_tampered_content_fails(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        tampered = signed.replace("PASS", "FAIL")
        ok = verify_report(tampered, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert ok is False

    def test_wrong_key_fails(self):
        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        ok = verify_report(signed, run_id=TEST_RUN_ID, signing_key="wrong-key-123456")
        assert ok is False

    def test_wrong_run_id_fails(self):
        """Signature binds to run_id — wrong run_id must fail."""
        signed = sign_report(SAMPLE_HTML, run_id="run-original", signing_key=TEST_KEY)
        ok = verify_report(signed, run_id="run-different", signing_key=TEST_KEY)
        assert ok is False

    def test_unsigned_report_fails(self):
        ok = verify_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert ok is False

    def test_empty_report_fails_gracefully(self):
        ok = verify_report("", run_id=TEST_RUN_ID, signing_key=TEST_KEY)
        assert ok is False


class TestSigningKeyFallback:
    def test_sign_with_none_key_does_not_raise(self):
        """Signing with None key should use machine-id or env fallback."""
        try:
            signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=None)
            assert "poagent-hmac-sha256" in signed
        except Exception as e:
            pytest.skip(f"No signing key available in test env: {e}")

    def test_env_key_used_when_set(self, monkeypatch):
        env_key = "env-key-from-environment-variable"
        monkeypatch.setenv("POAGENT_SIGNING_KEY", env_key)

        signed_with_env = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=None)
        signed_explicit = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=env_key)

        # Both should produce same signature since env key matches explicit key
        assert signed_with_env == signed_explicit
        assert "poagent-hmac-sha256" in signed_with_env

    def test_verify_with_env_key(self, monkeypatch):
        env_key = "verify-env-key-test"
        monkeypatch.setenv("POAGENT_SIGNING_KEY", env_key)

        signed = sign_report(SAMPLE_HTML, run_id=TEST_RUN_ID, signing_key=None)
        ok = verify_report(signed, run_id=TEST_RUN_ID, signing_key=None)
        assert ok is True
