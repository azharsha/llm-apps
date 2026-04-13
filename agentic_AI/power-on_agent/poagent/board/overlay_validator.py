"""[N-SG-05, FINAL-S5] DTS overlay validator.

Runs immediately after Agent 13 emits the overlay. Python-only, no LLM.
Blocks the pipeline on any hard error.

Also handles headless CI overlay confirmation via overlay_confirm_mode config.
"""

from __future__ import annotations

import subprocess
import sys
import structlog
from dataclasses import dataclass, field
from typing import Optional

from poagent.board.dts_parser import parse_po_agent_properties
from poagent.codes import (
    BOUNDS_VIOLATION,
    ZERO_VALUE_ERROR,
    UNKNOWN_PROPERTY,
    NO_CRITICAL_RAILS,
    SUSPICIOUS_LOW_VOLTAGE,
)

log = structlog.get_logger(__name__)


# Numeric bounds for po-agent,* properties
# [O-01] 100mV lower bound (not 500mV — modern SoCs have sub-500mV rails)
BOUNDS: dict[str, tuple[int, int]] = {
    "po-agent,expected-mv":              (100, 5000),
    "po-agent,tolerance-pct":            (1, 20),
    "po-agent,expected-pcie-gen":        (1, 5),
    "po-agent,expected-link-width":      (1, 16),
    "po-agent,expected-ports-usb3":      (0, 32),
    "po-agent,expected-ports-usb2":      (0, 32),
    "po-agent,expected-unsafe-shutdowns": (0, 1000),
    "po-agent,expected-microcode-rev":   (0x01, 0xFFFF),
    "po-agent,physically-present":       (0, 1),
}

# [FINAL-S5] Properties exempt from numeric bounds checking
BOUNDS_EXEMPT: frozenset[str] = frozenset({
    "po-agent,human-reviewed",    # commit-time attestation; value <1> is correct by definition
    "po-agent,silicon-stepping",  # free-form string override (e.g. "B1"); no numeric bounds
    "po-agent,low-confidence",    # comment marker; not a measurement
    "po-agent,critical",          # flag property; no value
    "po-agent,expected-connectors",  # string list; not numeric
})


@dataclass
class ValidationReport:
    """Result of overlay_validator.validate_overlay()."""
    overlay_path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        if self.is_valid and not self.warnings:
            return f"PASS — all po-agent,* properties in bounds: {self.overlay_path}"
        lines = []
        for e in self.errors:
            lines.append(f"ERROR: {e}")
        for w in self.warnings:
            lines.append(f"WARNING: {w}")
        return "\n".join(lines)


class OverlayConfirmError(Exception):
    """Raised when overlay confirmation requirement is not met."""


def validate_overlay(overlay_path: str) -> ValidationReport:
    """Validate a po-agent-overlay.dts file.

    Checks:
      1. DTS syntax via `dtc`
      2. All po-agent,* property bounds
      3. Zero-value errors for critical properties
      4. Sub-500mV warning (INFO)
      5. No critical rails declared warning

    Returns ValidationReport. Hard errors → report.is_valid == False.
    """
    report = ValidationReport(overlay_path=overlay_path)

    # Check 1 — DTS syntax via dtc
    result = subprocess.run(
        ["dtc", "-I", "dts", "-O", "dtb", "-o", "/dev/null", overlay_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        report.errors.append(
            f"{BOUNDS_VIOLATION}: dtc rejected overlay:\n{result.stderr.strip()}"
        )

    # Read overlay text
    try:
        with open(overlay_path, encoding="utf-8", errors="replace") as fh:
            overlay_text = fh.read()
    except OSError as exc:
        report.errors.append(f"Cannot read overlay file: {exc}")
        return report

    props = parse_po_agent_properties(overlay_text)

    # Check 2 — bounds
    for node, prop, value in props:
        if prop in BOUNDS_EXEMPT:
            continue
        if prop in BOUNDS:
            lo, hi = BOUNDS[prop]
            try:
                v = int(value)
                if not (lo <= v <= hi):
                    report.errors.append(
                        f"{BOUNDS_VIOLATION}: {node} {prop} = {value} "
                        f"(expected {lo}–{hi})"
                    )
            except (TypeError, ValueError):
                pass  # non-numeric — skip bounds check
        elif isinstance(value, (int, float)):
            report.warnings.append(
                f"{UNKNOWN_PROPERTY}: {node} {prop} = {value} "
                f"(not in BOUNDS or BOUNDS_EXEMPT — add to overlay_validator.py)"
            )

    # Check 3 — zero value errors for critical properties
    for node, prop, value in props:
        if value == 0 and prop in ("po-agent,expected-mv", "po-agent,expected-pcie-gen"):
            report.errors.append(
                f"{ZERO_VALUE_ERROR}: {node} {prop} = <0> — "
                f"LLM hallucination likely. No rail has 0mV nominal."
            )

    # Check 3b — sub-500mV INFO warning [O-01]
    for node, prop, value in props:
        if prop == "po-agent,expected-mv":
            try:
                v = int(value)
                if 100 <= v < 500:
                    report.warnings.append(
                        f"{SUSPICIOUS_LOW_VOLTAGE}: {node} expected-mv = {v}mV "
                        f"(sub-500mV rail — valid on modern SoCs but verify rail name "
                        f"mapping is correct)"
                    )
            except (TypeError, ValueError):
                pass

    # Check 4 — no critical rails declared
    critical_rails = [n for n, p, v in props if p == "po-agent,critical"]
    if not critical_rails:
        report.warnings.append(
            f"{NO_CRITICAL_RAILS}: overlay declares no po-agent,critical rails. "
            f"Rail Sanity Barrier will have nothing to check. "
            f"Did the LLM fail to extract rail criticality from the schematic?"
        )

    log.info(
        "overlay_validated",
        overlay_path=overlay_path,
        errors=len(report.errors),
        warnings=len(report.warnings),
    )
    return report


def check_overlay_confirmation(overlay_path: str, config: object) -> None:
    """[FINAL-S5] Enforce overlay confirmation based on overlay_confirm_mode.

    Modes:
      interactive  — require TTY prompt (default; fails in headless CI)
      pre_validated — check for po-agent,human-reviewed = <1> in overlay
      strict       — require --confirm-overlay CLI flag unconditionally

    Raises OverlayConfirmError if confirmation requirement not met.
    """
    mode: str = getattr(config, "overlay_confirm_mode", "interactive")

    if mode == "interactive":
        if not sys.stdin.isatty():
            raise OverlayConfirmError(
                "overlay_confirm_mode=interactive but no TTY available. "
                "Set overlay_confirm_mode=pre_validated for headless CI, "
                "or run --validate-overlay at commit time."
            )
        # Block on interactive prompt
        print(f"\nReview complete? Type YES to confirm overlay {overlay_path}: ", end="")
        answer = sys.stdin.readline().strip()
        if answer.upper() != "YES":
            raise OverlayConfirmError("Overlay review not confirmed by user.")

    elif mode == "pre_validated":
        with open(overlay_path, encoding="utf-8", errors="replace") as fh:
            overlay_text = fh.read()
        props = parse_po_agent_properties(overlay_text)
        reviewed = any(
            prop == "po-agent,human-reviewed" and int(value) == 1
            for _, prop, value in props
        )
        if not reviewed:
            raise OverlayConfirmError(
                "overlay_confirm_mode=pre_validated but po-agent,human-reviewed "
                "not found in overlay. "
                f"Run: poagent --validate-overlay {overlay_path}  then commit the result."
            )

    elif mode == "strict":
        if not getattr(config, "confirm_overlay_flag_set", False):
            raise OverlayConfirmError(
                "overlay_confirm_mode=strict: --confirm-overlay flag required. "
                "Refusing to proceed without explicit flag."
            )

    else:
        raise OverlayConfirmError(f"Unknown overlay_confirm_mode: {mode!r}")


def write_human_reviewed_flag(overlay_path: str) -> None:
    """Write po-agent,human-reviewed = <1> into overlay DTS root node.

    Called by `poagent --validate-overlay` after engineer confirms review.
    Appends the property to the root / { ... } block.
    """
    with open(overlay_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    # Check if already present
    if "po-agent,human-reviewed" in text:
        log.info("human_reviewed_already_set", overlay_path=overlay_path)
        return

    # Insert into root node (first / { block)
    import re
    # Find root node opening
    m = re.search(r"(/\s*\{)", text)
    if m:
        insert_pos = text.find("{", m.start()) + 1
        reviewed_prop = "\n\tpo-agent,human-reviewed = <1>;\t/* set by: poagent --validate-overlay */"
        text = text[:insert_pos] + reviewed_prop + text[insert_pos:]
    else:
        # Prepend a root node wrapper
        text = (
            "/ {\n"
            "\tpo-agent,human-reviewed = <1>;\t/* set by: poagent --validate-overlay */\n"
            "};\n" + text
        )

    with open(overlay_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    log.info("human_reviewed_flag_written", overlay_path=overlay_path)
