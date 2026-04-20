"""
wave_analyzer.py — Phase 3c v3c.1.0

Derives wavefront / engine stall signals from a HardwareContext + LogEvent.

Public symbol: analyse_waves(ctx, event) -> HardwareContext
"""

from __future__ import annotations

import re
from typing import Any

from soctriage.core.hardware_decode import HardwareContext

__all__ = ["analyse_waves"]

# ── Ring / engine name mapping ────────────────────────────────────────────────

_RING_NAME_MAP: dict[str, str] = {
    "gfx_0":     "GFX",
    "sdma0":     "SDMA",
    "bcs0":      "BLT",
    "vcs0":      "VIDEO",
    "adreno":    "GPU",
    "gr_engine": "GR",
}

# Also handle numbered variants e.g. gfx_1, sdma1, bcs1, vcs1
_RING_PATTERN_RE = re.compile(
    r"\b(gfx_\d+|sdma\d+|bcs\d+|vcs\d+|adreno|gr_engine)\b",
    re.IGNORECASE,
)

# Timeout pattern in raw text
_TIMEOUT_RE = re.compile(r"\btimeout\b", re.IGNORECASE)
_RESET_RE   = re.compile(r"\breset\b", re.IGNORECASE)

# Ring head/tail patterns for WH-01
_HEAD_RE = re.compile(r"\bRING_HEAD\s*[=:]\s*(?:0x)?([0-9A-Fa-f]+)", re.IGNORECASE)
_TAIL_RE = re.compile(r"\bRING_TAIL\s*[=:]\s*(?:0x)?([0-9A-Fa-f]+)", re.IGNORECASE)


def analyse_waves(ctx: HardwareContext, event: Any) -> HardwareContext:
    """
    Add/update derived_signals in ctx based on wave/ring analysis heuristics.

    Heuristics:
      WH-01: timeout token + ring head == ring tail → no_forward_progress
      WH-02: cp_stalled=True or CP_STALLED_STAT1!=0 → engine_stalled
      WH-03: mmhub_fault or qcom_smmu_fault or "SMMU context fault" → memory_translation_fault
      WH-04: guc_alive=False or gsp_boot_fail or psp_boot_fail or adsp_ssr → firmware_unresponsive
      WH-05: "reset" token in raw_text → reset_in_progress
      WH-06: ring name found → suspect_ip=<mapped engine name>

    Returns the SAME ctx object (mutated in place).
    """
    raw_text: str = getattr(event, "raw_text", "") or ""
    sigs = ctx.derived_signals

    # WH-01: timeout + ring head == ring tail → no_forward_progress
    if _TIMEOUT_RE.search(raw_text):
        head_match = _HEAD_RE.search(raw_text)
        tail_match = _TAIL_RE.search(raw_text)
        if head_match and tail_match:
            try:
                head_val = int(head_match.group(1), 16)
                tail_val = int(tail_match.group(1), 16)
                if head_val == tail_val:
                    sigs["no_forward_progress"] = True
            except ValueError:
                pass
        # Also set no_forward_progress if ring_stall already set
        if sigs.get("ring_stall"):
            sigs["no_forward_progress"] = True

    # WH-02: cp_stalled signal or any CP_STALLED_STAT1 register != 0
    cp_stalled = sigs.get("cp_stalled", False)
    if not cp_stalled:
        for reg in ctx.registers:
            if reg.name == "CP_STALLED_STAT1" and reg.raw_value != 0:
                cp_stalled = True
                break
    if cp_stalled:
        sigs["engine_stalled"] = True

    # WH-03: mmhub_fault or qcom_smmu_fault or "SMMU context fault" in raw_text
    if (
        sigs.get("mmhub_fault")
        or sigs.get("qcom_smmu_fault")
        or re.search(r"\bSMMU\s+context\s+fault\b", raw_text, re.IGNORECASE)
        or sigs.get("gtt_fault")
    ):
        sigs["memory_translation_fault"] = True

    # WH-04: firmware unresponsive signals
    guc_alive = sigs.get("guc_alive")   # may be False explicitly
    if (
        guc_alive is False
        or sigs.get("gsp_boot_fail")
        or sigs.get("psp_boot_fail")
        or sigs.get("adsp_ssr")
        or sigs.get("cdsp_ssr")
        or sigs.get("slpi_ssr")
    ):
        sigs["firmware_unresponsive"] = True

    # WH-05: reset token in raw_text → reset_in_progress
    if _RESET_RE.search(raw_text):
        sigs["reset_in_progress"] = True

    # WH-06: ring name → suspect_ip
    m = _RING_PATTERN_RE.search(raw_text)
    if m:
        ring_token = m.group(1).lower()
        # Try exact match first, then prefix match for numbered variants
        ip = _RING_NAME_MAP.get(ring_token)
        if ip is None:
            for prefix, mapped_ip in _RING_NAME_MAP.items():
                if ring_token.startswith(prefix.rstrip("0")) and prefix[-1].isdigit() is False:
                    # Handle gfx_1, gfx_2 etc → GFX
                    if re.match(r"^" + re.escape(prefix.rstrip("0")), ring_token):
                        ip = mapped_ip
                        break
            if ip is None:
                # Generalised: gfx_N → GFX, sdmaN → SDMA, bcsN → BLT, vcsN → VIDEO
                if ring_token.startswith("gfx_"):
                    ip = "GFX"
                elif ring_token.startswith("sdma"):
                    ip = "SDMA"
                elif ring_token.startswith("bcs"):
                    ip = "BLT"
                elif ring_token.startswith("vcs"):
                    ip = "VIDEO"
        if ip:
            sigs["suspect_ip"] = ip

    return ctx
