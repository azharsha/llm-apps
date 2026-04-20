"""
test_stall_classifier.py — Phase 3c v3c.1.0
16 tests for stall_classifier.classify_stall()
Expected: 16 PASSED, 0 FAILED
"""

from __future__ import annotations

import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.tokenizer import LogToken
from soctriage.core.hardware_decode import HardwareContext, HardwareRegister
from soctriage.core.stall_classifier import classify_stall

# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(raw: str = "") -> LogToken:
    return LogToken(
        line_no=1,
        raw=raw,
        token_type="gpu_event",
        arch="x86_64",
        chip_gen="amd_rdna3",
        kernel_ver="6.1",
        timestamp=None,
        is_duplicate=False,
        confidence=1.0,
    )


def _make_event(
    raw_text: str = "",
    event_type: str = "gpu_hang",
    chip_gen: str = "amd_rdna3",
) -> LogEvent:
    tok = _tok(raw_text)
    return LogEvent(
        event_id=1,
        event_type=event_type,
        severity="critical",
        subsystem="gpu",
        ip_block="GFX",
        tokens=[tok],
        start_line=1,
        end_line=1,
        arch="x86_64",
        chip_gen=chip_gen,
        kernel_ver="6.1",
        confidence=0.9,
        raw_text=raw_text,
        has_call_trace=False,
        has_registers=True,
        provider_name="AMD RDNA/CDNA",
    )


def _make_ctx(
    derived_signals: dict | None = None,
    registers: list | None = None,
) -> HardwareContext:
    return HardwareContext(
        provider_name="generic",
        chip_gen="amd_rdna3",
        registers=registers or [],
        derived_signals=derived_signals or {},
        stall_type="unknown_hardware_fault",
        stall_confidence=0.0,
        evidence_lines=[1],
        notes=[],
    )


def _make_reg(name: str, value: int = 1) -> HardwareRegister:
    return HardwareRegister(
        name=name,
        raw_value=value,
        width_bits=32,
        decoded_fields={},
        source_line=1,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_firmware_boot_fail_priority_over_gpu_stall():
    """firmware_boot_fail takes priority even when engine_stalled is also set."""
    ctx = _make_ctx({"psp_boot_fail": True, "engine_stalled": True})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "firmware_boot_fail"


def test_firmware_runtime_crash_from_adsp_ssr():
    """adsp_ssr=True → firmware_runtime_crash."""
    ctx = _make_ctx({"adsp_ssr": True})
    event = _make_event(event_type="soc_crash")
    result = classify_stall(ctx, event)
    assert result.stall_type == "firmware_runtime_crash"


def test_memory_translation_fault_from_mmhub():
    """mmhub_fault=True → memory_translation_fault."""
    ctx = _make_ctx({"mmhub_fault": True})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "memory_translation_fault"


def test_ras_uncorrectable_from_ras_ue():
    """ras_ue=True → ras_uncorrectable."""
    ctx = _make_ctx({"ras_ue": True})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "ras_uncorrectable"


def test_reset_storm_requires_reset_signal():
    """reset_in_progress + gpu_reset event_type → reset_storm."""
    ctx = _make_ctx({"reset_in_progress": True})
    event = _make_event(event_type="gpu_reset")
    result = classify_stall(ctx, event)
    assert result.stall_type == "reset_storm"


def test_gpu_hard_stall_from_engine_stalled():
    """engine_stalled=True (no higher-priority signals) → gpu_hard_stall."""
    ctx = _make_ctx({"engine_stalled": True})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "gpu_hard_stall"


def test_power_gating_fault_from_rpmh_timeout():
    """rpmh_timeout=True (no higher-priority signals) → power_gating_fault."""
    ctx = _make_ctx({"rpmh_timeout": True})
    event = _make_event(event_type="power_fault")
    result = classify_stall(ctx, event)
    assert result.stall_type == "power_gating_fault"


def test_unknown_hardware_fault_default():
    """No matching signals → unknown_hardware_fault."""
    ctx = _make_ctx({"some_other_signal": 42})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "unknown_hardware_fault"


def test_confidence_in_range():
    """Confidence score is always between 0.0 and 1.0."""
    ctx = _make_ctx({})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert 0.0 <= result.stall_confidence <= 1.0


def test_confidence_higher_with_multiple_signals():
    """More signals → higher confidence than zero signals."""
    ctx_empty = _make_ctx({})
    ctx_rich = _make_ctx({"cp_stalled": True, "engine_stalled": True})
    event = _make_event()
    classify_stall(ctx_empty, event)
    classify_stall(ctx_rich, event)
    assert ctx_rich.stall_confidence > ctx_empty.stall_confidence


def test_confidence_caps_at_one():
    """Confidence never exceeds 1.0 even with maximum signals."""
    # Load up all bonuses: registers + 2 signals + matching event type + known stall + bool true
    regs = [_make_reg("CP_STALLED_STAT1", 1), _make_reg("GRBM_STATUS", 0x20)]
    ctx = _make_ctx(
        {"engine_stalled": True, "cp_stalled": True, "no_forward_progress": True},
        registers=regs,
    )
    event = _make_event(event_type="gpu_hang")
    result = classify_stall(ctx, event)
    assert result.stall_confidence <= 1.0


def test_classify_stall_sets_notes_when_unknown():
    """When stall_type is unknown_hardware_fault, a note is added."""
    ctx = _make_ctx({})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.stall_type == "unknown_hardware_fault"
    assert len(result.notes) > 0


def test_evidence_lines_preserved():
    """Evidence lines from parse phase are preserved after classification."""
    ctx = _make_ctx({})
    ctx.evidence_lines = [5, 10, 15]
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result.evidence_lines == [5, 10, 15]


def test_register_presence_increases_confidence():
    """Having registers increases confidence vs no registers."""
    ctx_no_regs = _make_ctx({"cp_stalled": True}, registers=[])
    ctx_with_regs = _make_ctx({"cp_stalled": True}, registers=[_make_reg("CP_STALLED_STAT1", 1)])
    event = _make_event()
    classify_stall(ctx_no_regs, event)
    classify_stall(ctx_with_regs, event)
    assert ctx_with_regs.stall_confidence > ctx_no_regs.stall_confidence


def test_event_type_affects_confidence():
    """gpu_hang event_type gives higher confidence than power_fault."""
    ctx1 = _make_ctx({"engine_stalled": True}, registers=[_make_reg("CP_STALLED_STAT1", 1)])
    ctx2 = _make_ctx({"engine_stalled": True}, registers=[_make_reg("CP_STALLED_STAT1", 1)])
    event_gpu = _make_event(event_type="gpu_hang")
    event_pwr = _make_event(event_type="power_fault")
    classify_stall(ctx1, event_gpu)
    classify_stall(ctx2, event_pwr)
    assert ctx1.stall_confidence > ctx2.stall_confidence


def test_classify_returns_same_ctx_object():
    """classify_stall must return the same HardwareContext object."""
    ctx = _make_ctx({})
    event = _make_event()
    result = classify_stall(ctx, event)
    assert result is ctx
