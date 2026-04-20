"""
scan_dump_parser.py — Phase 3c v3c.1.0

SoC-agnostic register parser.  Scans LogEvent.raw_text for:
  - hardware register hex dumps (NAME=0xHEX, NAME: 0xHEX, NAME=HEX)
  - firmware state tokens (ADSP state=SSR, SPMI timeout, etc.)
  - vendor-specific ring/engine stall indicators

Public symbol: parse_registers(event, provider=None) -> HardwareContext | None
"""

from __future__ import annotations

import re
from typing import Any

from soctriage.core.hardware_decode import HardwareContext, HardwareRegister

__all__ = ["parse_registers", "REGISTER_RE"]

# ── Master register regex ─────────────────────────────────────────────────────

# Matches: NAME=0xHEX  NAME: 0xHEX  NAME = HEX  NAME[0]=0xHEX
# Case-insensitive so "0x" and "0X" both match; name is uppercased after.
# The hex group is terminated by a word boundary (not followed by more letters)
# to avoid mistaking log prefixes like "amdgpu: CP_..." as registers.
REGISTER_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_\[\]\.]+)\s*(?:=|:)\s*(?:0x)?(?P<hex>[0-9A-Fa-f]{1,16})(?![0-9A-Za-z_])",
    re.IGNORECASE,
)

# ── Firmware / state token patterns ──────────────────────────────────────────

_ADSP_SSR_RE  = re.compile(r"\bADSP\s+state\s*=\s*SSR\b", re.IGNORECASE)
_CDSP_SSR_RE  = re.compile(r"\bCDSP\s+state\s*=\s*SSR\b", re.IGNORECASE)
_SLPI_SSR_RE  = re.compile(r"\bSLPI\s+state\s*=\s*SSR\b", re.IGNORECASE)
_SPMI_RE      = re.compile(r"\bSPMI\s+timeout\b", re.IGNORECASE)
_RPMH_RE      = re.compile(r"\bRPMH\s+timeout\b", re.IGNORECASE)
_SMMU_FAULT_RE = re.compile(r"\bSMMU\s+context\s+fault\b", re.IGNORECASE)
_RING_STALL_RE = re.compile(r"\bRING\b.*\btimeout\b", re.IGNORECASE)
_RING_NAME_RE  = re.compile(
    r"\b(?:ring\s+)?(gfx_\d+|sdma\d+|bcs\d+|vcs\d+|adreno|gr_engine)\b",
    re.IGNORECASE,
)
_BAR2_FAULT_RE = re.compile(r"\bBAR2[_\s]FAULT\b", re.IGNORECASE)
_GSP_FAIL_TEXT_RE = re.compile(r"\bGSP\s+firmware\s+failed\b", re.IGNORECASE)

# Malformed register: name + = or : + 0x + non-hex chars (to detect and note)
_MALFORMED_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_\[\]\.]+)\s*(?:=|:)\s*0x(?P<bad>[0-9A-Fa-f]*[G-Zg-z][^\s]*)",
    re.IGNORECASE,
)

# ── AMD decode table ──────────────────────────────────────────────────────────

# Register name → list of (mask_or_shift, field_name, signal_key, signal_value_fn)
# Each entry is: (bit_mask, field_name, signal_key, value_fn)
# value_fn takes the raw_value and returns the signal value (True/False/int/etc.)
_AMD_REGISTER_MAP: dict[str, list[tuple]] = {
    "GRBM_STATUS": [
        (1 << 31, "GUI_ACTIVE", "gui_active", lambda v: bool(v & (1 << 31))),
        (1 << 5,  "CP_BUSY",    "cp_busy",    lambda v: bool(v & (1 << 5))),
    ],
    "CP_STALLED_STAT1": [
        (0xFFFFFFFF, "CP_STALLED", "cp_stalled", lambda v: v != 0),
    ],
    "MMHUB_STATUS": [
        (0xFFFFFFFF, "MMHUB_FAULT", "mmhub_fault", lambda v: v != 0),
    ],
    "PSP_STATUS": [
        (0xFFFFFFFF, "PSP_BOOT_FAIL", "psp_boot_fail", lambda v: v != 0),
    ],
    "RAS_ERR_STATUS": [
        (0xFFFFFFFF, "RAS_UE", "ras_ue", lambda v: v != 0),
    ],
}

# ── Intel decode table ────────────────────────────────────────────────────────

_INTEL_REGISTER_MAP: dict[str, list[tuple]] = {
    "GUC_STATUS": [
        # handled specially by name pattern GUC_STATUS[0]
        (0xFFFFFFFF, "GUC_ALIVE", "guc_alive", lambda v: v != 0),
        (0xFFFFFFFF, "GUC_BOOTING", "guc_booting", lambda v: v == 4),
    ],
    "GT_RESET_REASON": [
        (0xFFFFFFFF, "GT_RESET_SEEN", "gt_reset_seen", lambda v: v != 0),
    ],
    "GTT_FAULT_STATUS": [
        (0xFFFFFFFF, "GTT_FAULT", "gtt_fault", lambda v: v != 0),
    ],
}

# ── NVIDIA decode table ───────────────────────────────────────────────────────

_NVIDIA_REGISTER_MAP: dict[str, list[tuple]] = {
    "GSP_BOOT_STATUS": [
        (0xFFFFFFFF, "GSP_BOOT_FAIL", "gsp_boot_fail", lambda v: v != 0),
    ],
    "NV_PGRAPH_STATUS": [
        (0xFFFFFFFF, "GR_ENGINE_FAULT", "gr_engine_fault", lambda v: v != 0),
    ],
    "FB_ECC_STATUS": [
        (0xFFFFFFFF, "FB_ECC_UE", "fb_ecc_ue", lambda v: v != 0),
    ],
}


def _provider_name_from(event: Any, provider: Any) -> str:
    """Derive a lower-cased provider name string."""
    if provider is not None and hasattr(provider, "name"):
        name_val: str = str(provider.name())
        return name_val.lower()
    # Fall back to event attributes
    pn: str = getattr(event, "provider_name", "") or ""
    return pn.lower()


def _chip_gen_from(event: Any) -> str:
    return getattr(event, "chip_gen", "unknown") or "unknown"


def _decode_register_fields(
    name: str,
    raw_value: int,
    provider_hint: str,
) -> tuple[dict, dict]:
    """
    Return (decoded_fields, derived_signals) for a known register.
    decoded_fields: field_name → bool/int
    derived_signals: signal_key → value
    """
    decoded_fields: dict = {}
    derived_signals: dict = {}

    # Normalise name: strip bracket suffix for lookup but keep GUC_STATUS[0]
    bare_name = re.sub(r"\[.*?\]", "", name)

    # AMD
    entries = _AMD_REGISTER_MAP.get(bare_name) or _AMD_REGISTER_MAP.get(name)
    if entries:
        for _mask, field_name, signal_key, vfn in entries:
            val = vfn(raw_value)
            decoded_fields[field_name] = val
            derived_signals[signal_key] = val
        return decoded_fields, derived_signals

    # Intel
    entries = _INTEL_REGISTER_MAP.get(bare_name) or _INTEL_REGISTER_MAP.get(name)
    if entries:
        if bare_name == "GUC_STATUS" or name.startswith("GUC_STATUS"):
            # Special: guc_alive = (value != 0), guc_booting = (value == 4)
            guc_alive = raw_value != 0
            guc_booting = raw_value == 4
            decoded_fields["GUC_ALIVE"] = guc_alive
            decoded_fields["GUC_BOOTING"] = guc_booting
            derived_signals["guc_alive"] = guc_alive
            if guc_booting:
                derived_signals["guc_booting"] = True
        else:
            for _mask, field_name, signal_key, vfn in entries:
                val = vfn(raw_value)
                decoded_fields[field_name] = val
                derived_signals[signal_key] = val
        return decoded_fields, derived_signals

    # NVIDIA
    entries = _NVIDIA_REGISTER_MAP.get(bare_name) or _NVIDIA_REGISTER_MAP.get(name)
    if entries:
        for _mask, field_name, signal_key, vfn in entries:
            val = vfn(raw_value)
            decoded_fields[field_name] = val
            derived_signals[signal_key] = val
        return decoded_fields, derived_signals

    return decoded_fields, derived_signals


def parse_registers(event: Any, provider: Any = None) -> "HardwareContext | None":
    """
    Scan LogEvent.raw_text and extract:
    1. named hardware registers with integer values
    2. firmware state tokens (GuC dead, ADSP SSR, PSP fail, GSP timeout)
    3. lightweight derived signals from known register names

    Returns HardwareContext if any evidence found, else None.
    Never raises on malformed hex — records a note and continues.
    """
    raw_text: str = getattr(event, "raw_text", "") or ""
    provider_hint = _provider_name_from(event, provider)
    chip_gen = _chip_gen_from(event)

    registers: list[HardwareRegister] = []
    derived_signals: dict = {}
    evidence_lines: list[int] = []
    notes: list[str] = []

    lines = raw_text.splitlines()

    # ── Pass 1: regex register scan ──────────────────────────────────────────
    for line_idx, line in enumerate(lines):
        # Check for malformed hex values first (0x + non-hex chars)
        for malf in _MALFORMED_RE.finditer(line):
            bad_name = malf.group("name").upper()
            notes.append(f"ignored malformed register {bad_name} at line {line_idx + 1}")

        # REGISTER_RE is case-insensitive; normalise matched name to uppercase
        for match in REGISTER_RE.finditer(line):
            name = match.group("name").upper()
            hex_str = match.group("hex")

            # Validate hex (belt-and-suspenders — REGISTER_RE already filters)
            try:
                raw_value = int(hex_str, 16)
            except ValueError:
                notes.append(f"ignored malformed register {name} at line {line_idx + 1}")
                continue

            # Determine width: >8 hex chars → 64-bit, else 32-bit
            width_bits = 64 if len(hex_str) > 8 else 32

            # Decode known fields
            decoded_fields, reg_signals = _decode_register_fields(
                name, raw_value, provider_hint
            )
            derived_signals.update(reg_signals)

            reg = HardwareRegister(
                name=name,
                raw_value=raw_value,
                width_bits=width_bits,
                decoded_fields=decoded_fields,
                source_line=line_idx + 1,
            )
            registers.append(reg)
            evidence_lines.append(line_idx + 1)

    # ── Pass 2: firmware / state token scan ──────────────────────────────────
    for line_idx, line in enumerate(lines):
        ln = line_idx + 1

        if _ADSP_SSR_RE.search(line):
            derived_signals["adsp_ssr"] = True
            evidence_lines.append(ln)

        if _CDSP_SSR_RE.search(line):
            derived_signals["cdsp_ssr"] = True
            evidence_lines.append(ln)

        if _SLPI_SSR_RE.search(line):
            derived_signals["slpi_ssr"] = True
            evidence_lines.append(ln)

        if _SPMI_RE.search(line):
            derived_signals["spmi_fault"] = True
            evidence_lines.append(ln)

        if _RPMH_RE.search(line):
            derived_signals["rpmh_timeout"] = True
            evidence_lines.append(ln)

        if _SMMU_FAULT_RE.search(line):
            derived_signals["qcom_smmu_fault"] = True
            evidence_lines.append(ln)

        if _RING_STALL_RE.search(line):
            derived_signals["ring_stall"] = True
            evidence_lines.append(ln)

        if _BAR2_FAULT_RE.search(line):
            derived_signals["bar2_fault"] = True
            evidence_lines.append(ln)

        if _GSP_FAIL_TEXT_RE.search(line):
            derived_signals["gsp_boot_fail"] = True
            evidence_lines.append(ln)

    # ── No evidence → return None ─────────────────────────────────────────────
    if not registers and not derived_signals:
        return None

    # Deduplicate evidence lines while preserving order
    seen: set[int] = set()
    unique_evidence: list[int] = []
    for ln in evidence_lines:
        if ln not in seen:
            seen.add(ln)
            unique_evidence.append(ln)

    # Determine provider name for context
    if not provider_hint or provider_hint in ("generic", ""):
        provider_name = "generic"
    else:
        provider_name = provider_hint

    return HardwareContext(
        provider_name=provider_name,
        chip_gen=chip_gen,
        registers=registers,
        derived_signals=derived_signals,
        stall_type="unknown_hardware_fault",   # set by stall_classifier
        stall_confidence=0.0,                   # set by stall_classifier
        evidence_lines=unique_evidence,
        notes=notes,
    )
