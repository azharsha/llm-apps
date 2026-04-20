"""
stall_classifier.py — Phase 3c v3c.1.0

Converts a HardwareContext (with derived_signals from the wave analyzer) into
a vendor-agnostic stall classification with a confidence score.

Public symbol: classify_stall(ctx, event) -> HardwareContext
"""

from __future__ import annotations

from typing import Any

from soctriage.core.hardware_decode import HardwareContext

__all__ = ["classify_stall"]


def _compute_stall_type(ctx: HardwareContext, event: Any) -> str:
    """
    Priority-ordered stall classification. First match wins.

    Priority:
    1. firmware_boot_fail  — psp/guc/gsp fail at boot
    2. firmware_runtime_crash — adsp/cdsp/slpi SSR
    3. memory_translation_fault — mmhub/gtt/smmu fault
    4. ras_uncorrectable — ECC/RAS UE
    5. reset_storm — reset_in_progress + gpu_reset/hang event type
    6. gpu_hard_stall — engine stalled or no forward progress
    7. power_gating_fault — rpmh timeout
    8. unknown_hardware_fault — fallback
    """
    sigs = ctx.derived_signals
    event_type = getattr(event, "event_type", "") or ""

    if (
        sigs.get("psp_boot_fail")
        or sigs.get("guc_alive") is False
        or sigs.get("gsp_boot_fail")
    ):
        return "firmware_boot_fail"

    if sigs.get("adsp_ssr") or sigs.get("cdsp_ssr") or sigs.get("slpi_ssr"):
        return "firmware_runtime_crash"

    if (
        sigs.get("memory_translation_fault")
        or sigs.get("mmhub_fault")
        or sigs.get("gtt_fault")
    ):
        return "memory_translation_fault"

    if sigs.get("ras_ue") or sigs.get("fb_ecc_ue"):
        return "ras_uncorrectable"

    if sigs.get("reset_in_progress") and event_type in {"gpu_reset", "gpu_hang"}:
        return "reset_storm"

    if sigs.get("engine_stalled") or sigs.get("no_forward_progress"):
        return "gpu_hard_stall"

    if sigs.get("rpmh_timeout"):
        return "power_gating_fault"

    return "unknown_hardware_fault"


def _compute_stall_confidence(ctx: HardwareContext, event: Any) -> float:
    """
    Confidence scoring:
      base:                 0.30
      +0.20 if registers present
      +0.15 if >= 2 derived signals
      +0.15 if event_type in {gpu_hang, firmware_fail, smmu_fault, soc_crash}
      +0.10 if stall_type != unknown_hardware_fault
      +0.10 if any bool True signal
      cap: 1.0
    """
    score = 0.30
    if ctx.registers:
        score += 0.20
    if len(ctx.derived_signals) >= 2:
        score += 0.15
    event_type = getattr(event, "event_type", "") or ""
    if event_type in {"gpu_hang", "firmware_fail", "smmu_fault", "soc_crash"}:
        score += 0.15
    if ctx.stall_type != "unknown_hardware_fault":
        score += 0.10
    if any(v is True for v in ctx.derived_signals.values() if isinstance(v, bool)):
        score += 0.10
    return min(score, 1.0)


def classify_stall(ctx: HardwareContext, event: Any) -> HardwareContext:
    """
    Set ctx.stall_type and ctx.stall_confidence based on derived_signals.
    Adds a note when classification falls back to unknown_hardware_fault.
    Returns the SAME ctx object.
    """
    ctx.stall_type = _compute_stall_type(ctx, event)
    ctx.stall_confidence = _compute_stall_confidence(ctx, event)

    if ctx.stall_type == "unknown_hardware_fault":
        ctx.notes.append(
            "no precise stall pattern matched; classified as unknown_hardware_fault"
        )

    return ctx
