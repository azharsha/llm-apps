"""HMAC-SHA-256 report signing and verification.

Signs the final HTML report to detect tampering.
The HMAC key is derived from the run_id and a site-level secret.

Signature is appended as an HTML comment at the end of the report:
  <!-- poagent-hmac-sha256: <hex_signature> -->

Verification reads that comment and recomputes over the report body
(everything before the signature comment).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_SIG_PATTERN = re.compile(
    r"<!-- poagent-hmac-sha256: ([0-9a-f]{64}) -->\s*$",
    re.MULTILINE,
)
_SIG_MARKER = "<!-- poagent-hmac-sha256: {sig} -->"

_ENV_SIGNING_KEY = "POAGENT_SIGNING_KEY"


def _get_signing_key(config_key: Optional[str] = None) -> bytes:
    """Get the HMAC signing key.

    Priority: env POAGENT_SIGNING_KEY → config key → derived from run machine id.
    Returns bytes.
    """
    key_str = (
        os.environ.get(_ENV_SIGNING_KEY, "")
        or config_key
        or _machine_id_key()
    )
    return key_str.encode("utf-8") if isinstance(key_str, str) else key_str


def _machine_id_key() -> str:
    """Fallback: derive key from /etc/machine-id."""
    try:
        machine_id = Path("/etc/machine-id").read_text().strip()
        return f"poagent-{machine_id}"
    except Exception:
        return "poagent-default-key-CHANGE-ME"


def sign_report(
    html_content: str,
    run_id: str,
    signing_key: Optional[str] = None,
) -> str:
    """Sign an HTML report and append the HMAC comment.

    Returns the HTML content with signature appended.
    """
    # Remove any existing signature
    html_body = _SIG_PATTERN.sub("", html_content).rstrip()

    key = _get_signing_key(signing_key)
    # Include run_id in the message to bind signature to this run
    message = f"run_id={run_id}\n{html_body}".encode("utf-8")

    sig = hmac.new(key, message, hashlib.sha256).hexdigest()
    signed = html_body + "\n" + _SIG_MARKER.format(sig=sig) + "\n"

    log.debug("report_signed", run_id=run_id, sig_prefix=sig[:8])
    return signed


def verify_report(
    html_content: str,
    run_id: str,
    signing_key: Optional[str] = None,
) -> bool:
    """Verify the HMAC signature of a signed HTML report.

    Returns True if signature is valid, False if tampered or missing.
    """
    m = _SIG_PATTERN.search(html_content)
    if not m:
        log.warning("report_signature_missing", run_id=run_id)
        return False

    stored_sig = m.group(1)
    html_body = _SIG_PATTERN.sub("", html_content).rstrip()

    key = _get_signing_key(signing_key)
    message = f"run_id={run_id}\n{html_body}".encode("utf-8")
    expected_sig = hmac.new(key, message, hashlib.sha256).hexdigest()

    valid = hmac.compare_digest(stored_sig, expected_sig)
    if valid:
        log.info("report_signature_valid", run_id=run_id)
    else:
        log.warning("report_signature_invalid", run_id=run_id,
                    stored_prefix=stored_sig[:8], expected_prefix=expected_sig[:8])
    return valid


def verify_report_file(
    report_path: str,
    run_id: str,
    signing_key: Optional[str] = None,
) -> bool:
    """Read and verify a report file. Returns True if valid."""
    try:
        content = Path(report_path).read_text(encoding="utf-8")
    except Exception as exc:
        log.error("report_read_failed", path=report_path, error=str(exc))
        return False
    return verify_report(content, run_id, signing_key)
