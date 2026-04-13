"""Credential management for PoAgent.

Resolves SSH keys and API keys from (in priority order):
  1. OS keyring (keyring library)
  2. Environment variables (POAGENT_ANTHROPIC_KEY, POAGENT_SSH_KEY, etc.)
  3. Config file values (passed in as fallback)

Secrets are NEVER written to disk by this module.
API key is validated by length (must be >= 20 chars).
SSH private key path is expanded for ~ and validated for existence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_KEYRING_SERVICE = "poagent"


def resolve_api_key(
    config_value: Optional[str] = None,
    keyring_account: str = "anthropic_api_key",
) -> str:
    """Resolve Anthropic API key.

    Priority: keyring → env POAGENT_ANTHROPIC_KEY / ANTHROPIC_API_KEY → config value.

    Raises ValueError if no key found.
    """
    # 1. Keyring
    try:
        import keyring
        val = keyring.get_password(_KEYRING_SERVICE, keyring_account)
        if val and len(val) >= 20:
            log.debug("api_key_from_keyring", account=keyring_account)
            return val
    except Exception:
        pass  # keyring not available or empty

    # 2. Environment
    for env_var in ("POAGENT_ANTHROPIC_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(env_var, "")
        if val and len(val) >= 20:
            log.debug("api_key_from_env", env_var=env_var)
            return val

    # 3. Config fallback
    if config_value and len(config_value) >= 20:
        log.debug("api_key_from_config")
        return config_value

    raise ValueError(
        "No Anthropic API key found. Set ANTHROPIC_API_KEY env var, "
        "use keyring, or provide api_key in config."
    )


def resolve_ssh_key(
    config_value: Optional[str] = None,
    keyring_account: str = "ssh_private_key_path",
) -> Optional[str]:
    """Resolve SSH private key path.

    Priority: keyring → env POAGENT_SSH_KEY_PATH → config value → ~/.ssh/id_rsa.

    Returns expanded path string or None if not found.
    """
    candidates: list[str] = []

    # 1. Keyring
    try:
        import keyring
        val = keyring.get_password(_KEYRING_SERVICE, keyring_account)
        if val:
            candidates.append(val)
    except Exception:
        pass

    # 2. Environment
    env_val = os.environ.get("POAGENT_SSH_KEY_PATH", "")
    if env_val:
        candidates.append(env_val)

    # 3. Config fallback
    if config_value:
        candidates.append(config_value)

    # 4. Default locations
    candidates.extend([
        "~/.ssh/id_rsa",
        "~/.ssh/id_ed25519",
        "~/.ssh/id_ecdsa",
    ])

    for candidate in candidates:
        expanded = Path(candidate.replace("~", str(Path.home())))
        if expanded.exists():
            log.debug("ssh_key_resolved", path=str(expanded))
            return str(expanded)

    log.debug("ssh_key_not_found")
    return None


def store_api_key(api_key: str, account: str = "anthropic_api_key") -> bool:
    """Store API key in OS keyring. Returns True on success."""
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, account, api_key)
        log.info("api_key_stored_in_keyring", account=account)
        return True
    except Exception as exc:
        log.warning("keyring_store_failed", error=str(exc))
        return False


def validate_api_key(api_key: str) -> None:
    """Validate API key format. Raises ValueError if invalid."""
    if not api_key or len(api_key) < 20:
        raise ValueError(
            f"API key too short ({len(api_key)} chars). "
            "Expected a valid Anthropic API key (>= 20 chars)."
        )


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """Mask a secret for logging purposes."""
    if len(secret) <= visible_chars:
        return "***"
    return secret[:visible_chars] + "..." + secret[-visible_chars:]
