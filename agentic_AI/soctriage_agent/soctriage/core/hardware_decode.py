"""
hardware_decode.py — Phase 3c v3c.1.0

Public decode pipeline for Phase 3c: HardwareContext, HardwareRegister,
and the decode_hardware() entry point.

Pipeline: parse_registers → analyse_waves → classify_stall → attach to event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["HardwareRegister", "HardwareContext", "decode_hardware"]


# ── Public dataclasses ────────────────────────────────────────────────────────


@dataclass
class HardwareRegister:
    """One parsed hardware register from a log event."""
    name: str              # e.g. "GRBM_STATUS", "CP_STALLED_STAT1"
    raw_value: int         # decoded from hex string
    width_bits: int        # 32 or 64
    decoded_fields: dict   # {"CP_BUSY": True, "GUI_ACTIVE": False}
    source_line: int       # original line number from the LogEvent


@dataclass
class HardwareContext:
    """Structured hardware decode result attached to a LogEvent."""
    provider_name: str                        # intel | qualcomm | amd | nvidia | generic
    chip_gen: str                             # inherited from event
    registers: list[HardwareRegister]         # all parsed registers
    derived_signals: dict                     # cp_stalled, mmhub_fault, guc_alive, etc.
    stall_type: str                           # one of 8 vendor-agnostic categories
    stall_confidence: float                   # 0.0–1.0
    evidence_lines: list[int]                 # line numbers that drove classification
    notes: list[str]                          # human-readable decoder notes

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dictionary."""
        return {
            "provider_name": self.provider_name,
            "chip_gen": self.chip_gen,
            "registers": [
                {
                    "name": r.name,
                    "raw_value": r.raw_value,
                    "width_bits": r.width_bits,
                    "decoded_fields": r.decoded_fields,
                    "source_line": r.source_line,
                }
                for r in self.registers
            ],
            "derived_signals": dict(self.derived_signals),
            "stall_type": self.stall_type,
            "stall_confidence": round(self.stall_confidence, 4),
            "evidence_lines": list(self.evidence_lines),
            "notes": list(self.notes),
        }


# ── Pipeline entry point ──────────────────────────────────────────────────────


def decode_hardware(
    events: list,
    provider: Any = None,
) -> list:
    """
    Mutate each LogEvent in-place by attaching event.hardware_context when
    hardware evidence is present.

    Rules:
    - No raw register evidence → event.hardware_context = None
    - Unknown register names are preserved, not dropped
    - Never raises on malformed hex; records note and continues
    - Returns the SAME list object passed in

    Pipeline per event: parse_registers → analyse_waves → classify_stall
    """
    from soctriage.core.scan_dump_parser import parse_registers
    from soctriage.core.wave_analyzer import analyse_waves
    from soctriage.core.stall_classifier import classify_stall

    for event in events:
        ctx = parse_registers(event, provider=provider)
        if ctx is None:
            event.__dict__["hardware_context"] = None
            continue
        ctx = analyse_waves(ctx, event)
        ctx = classify_stall(ctx, event)
        event.__dict__["hardware_context"] = ctx

    return events
