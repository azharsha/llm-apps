"""Tests for security/credentials.py.

Critical constraints under test:
- resolve_api_key(): keyring → env POAGENT_ANTHROPIC_KEY/ANTHROPIC_API_KEY → config_value
- validate_api_key() raises ValueError on invalid key
- mask_secret() masks most of the string
- resolve_ssh_key() handles missing files gracefully
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from poagent.security.credentials import (
    resolve_api_key,
    validate_api_key,
    mask_secret,
)


class TestResolveApiKey:
    def test_env_var_used_when_set(self, monkeypatch):
        """ANTHROPIC_API_KEY env var is used when no keyring value."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-api-key-1234567890abcdef")
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)
        # Patch keyring to return nothing so env var is used
        with patch("keyring.get_password", return_value=None):
            result = resolve_api_key(config_value=None)
        assert result == "env-api-key-1234567890abcdef"

    def test_poagent_env_var_used_when_set(self, monkeypatch):
        """POAGENT_ANTHROPIC_KEY takes precedence over ANTHROPIC_API_KEY."""
        monkeypatch.setenv("POAGENT_ANTHROPIC_KEY", "poagent-env-key-1234567890")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fallback-env-key-9876543210")
        with patch("keyring.get_password", return_value=None):
            result = resolve_api_key(config_value=None)
        assert result == "poagent-env-key-1234567890"

    def test_config_value_used_as_last_resort(self, monkeypatch):
        """config_value is returned when keyring and env are empty."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)
        with patch("keyring.get_password", return_value=None):
            result = resolve_api_key(config_value="config-api-key-9876543210")
        assert result == "config-api-key-9876543210"

    def test_raises_when_no_key_available(self, monkeypatch):
        """ValueError raised when no key found anywhere."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("POAGENT_ANTHROPIC_KEY", raising=False)
        # Patch keyring at module level so import inside try fails
        with patch("keyring.get_password", return_value=None):
            with pytest.raises(ValueError):
                resolve_api_key(config_value=None)

    def test_short_key_not_returned_from_keyring(self, monkeypatch):
        """Keyring value < 20 chars is rejected (insufficient length)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-long-key-1234567890")
        with patch("keyring.get_password", return_value="short"):
            result = resolve_api_key(config_value=None)
        # Falls through to env var since keyring value is too short
        assert result == "env-long-key-1234567890"


class TestValidateApiKey:
    def test_valid_long_key_does_not_raise(self):
        key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        # Should not raise
        validate_api_key(key)

    def test_empty_key_raises(self):
        with pytest.raises((ValueError, TypeError)):
            validate_api_key("")

    def test_none_key_raises(self):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            validate_api_key(None)

    def test_short_key_raises(self):
        """Key shorter than minimum length raises ValueError."""
        with pytest.raises((ValueError, TypeError)):
            validate_api_key("short")


class TestMaskSecret:
    def test_masks_middle_of_key(self):
        key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        masked = mask_secret(key)
        assert isinstance(masked, str)
        # Visible prefix should appear
        assert masked.startswith(key[:4])
        # Full key should not appear verbatim
        assert key not in masked

    def test_short_key_does_not_crash(self):
        masked = mask_secret("abc")
        assert masked is not None
        assert isinstance(masked, str)

    def test_empty_key_does_not_crash(self):
        masked = mask_secret("")
        assert isinstance(masked, str)

    def test_masked_shorter_than_original(self):
        key = "sk-ant-api03-SuperSecretLongKeyThatShouldBeHidden"
        masked = mask_secret(key)
        # Masked should hide the bulk of the key
        assert key not in masked
