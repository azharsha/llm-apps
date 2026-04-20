"""
test_wave_analyzer.py — Phase 3c v3c.1.0
16 tests for wave_analyzer.analyse_waves()
Expected: 16 PASSED, 0 FAILED
"""

from __future__ import annotations

import json
import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.tokenizer import LogToken
from soctriage.core.hardware_decode import HardwareContext, HardwareRegister
from soctriage.core.wave_analyzer import analyse_waves

# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(raw: str = "", chip_gen: str = "amd_rdna3") -> LogToken:
    return LogToken(
        line_no=1,
        raw=raw,
        token_type="gpu_event",
        arch="x86_64",
        chip_gen=chip_gen,
        kernel_ver="6.1",
        timestamp=None,
        is_duplicate=False,
        confidence=1.0,
    )


def _make_event(
    raw_text: str,
    event_type: str = "gpu_hang",
    chip_gen: str = "amd_rdna3",
) -> LogEvent:
    tok = _tok(raw_text, chip_gen)
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
    registers: list[HardwareRegister] | None = None,
    provider_name: str = "generic",
    chip_gen: str = "amd_rdna3",
) -> HardwareContext:
    return HardwareContext(
        provider_name=provider_name,
        chip_gen=chip_gen,
        registers=registers or [],
        derived_signals=derived_signals or {},
        stall_type="unknown_hardware_fault",
        stall_confidence=0.0,
        evidence_lines=[],
        notes=[],
    )


def _make_reg(name: str, value: int) -> HardwareRegister:
    return HardwareRegister(
        name=name,
        raw_value=value,
        width_bits=32,
        decoded_fields={},
        source_line=1,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_wh01_timeout_plus_equal_heads_sets_no_forward_progress():
    """WH-01: timeout token + RING_HEAD == RING_TAIL → no_forward_progress=True."""
    raw = "engine reset failed, RING_HEAD=0x00000100 RING_TAIL=0x00000100 timeout"
    event = _make_event(raw)
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("no_forward_progress") is True


def test_wh02_cp_stalled_sets_engine_stalled():
    """WH-02: cp_stalled=True in derived_signals → engine_stalled=True."""
    event = _make_event("amdgpu: GPU hang")
    ctx = _make_ctx(derived_signals={"cp_stalled": True})
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("engine_stalled") is True


def test_wh03_mmhub_sets_translation_fault():
    """WH-03: mmhub_fault=True → memory_translation_fault=True."""
    event = _make_event("MMHUB error detected")
    ctx = _make_ctx(derived_signals={"mmhub_fault": True})
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("memory_translation_fault") is True


def test_wh04_firmware_fail_sets_unresponsive():
    """WH-04: guc_alive=False → firmware_unresponsive=True."""
    event = _make_event("GuC not alive")
    ctx = _make_ctx(derived_signals={"guc_alive": False})
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("firmware_unresponsive") is True


def test_wh05_reset_token_sets_reset_in_progress():
    """WH-05: 'reset' in raw_text → reset_in_progress=True."""
    event = _make_event("GPU reset attempt #1 failed")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("reset_in_progress") is True


def test_wh06_ring_name_maps_suspect_ip_gfx():
    """WH-06: ring 'gfx_0' in raw_text → suspect_ip='GFX'."""
    event = _make_event("amdgpu: ring gfx_0 timeout")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "GFX"


def test_wh06_ring_name_maps_suspect_ip_sdma():
    """WH-06: ring 'sdma0' in raw_text → suspect_ip='SDMA'."""
    event = _make_event("amdgpu: ring sdma0 timeout")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "SDMA"


def test_wave_analysis_preserves_existing_signals():
    """Existing signals in derived_signals are not erased."""
    event = _make_event("some log line")
    ctx = _make_ctx(derived_signals={"custom_signal": True})
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("custom_signal") is True


def test_no_signals_no_crash():
    """Empty raw_text and empty derived_signals does not crash."""
    event = _make_event("")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result is not None


def test_intel_bcs_ring_maps_blt_engine():
    """WH-06: ring 'bcs0' → suspect_ip='BLT'."""
    event = _make_event("i915: bcs0 ring timeout")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "BLT"


def test_intel_vcs_ring_maps_video_engine():
    """WH-06: ring 'vcs0' → suspect_ip='VIDEO'."""
    event = _make_event("i915: vcs0 ring timeout")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "VIDEO"


def test_qcom_adreno_timeout_maps_gpu():
    """WH-06: 'adreno' → suspect_ip='GPU'."""
    event = _make_event("kgsl: adreno hang detected", chip_gen="qcom_adreno")
    ctx = _make_ctx(chip_gen="qcom_adreno")
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "GPU"


def test_nvidia_gr_timeout_maps_gr_engine():
    """WH-06: 'gr_engine' → suspect_ip='GR'."""
    event = _make_event("nvidia: gr_engine timeout", chip_gen="nvidia_ga102")
    ctx = _make_ctx(chip_gen="nvidia_ga102")
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("suspect_ip") == "GR"


def test_memory_fault_plus_smmu_token_prioritises_translation():
    """WH-03: 'SMMU context fault' in raw_text → memory_translation_fault=True."""
    event = _make_event("arm-smmu: SMMU context fault detected on SID 0x12")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result.derived_signals.get("memory_translation_fault") is True


def test_analyse_waves_returns_same_ctx_object():
    """analyse_waves must return the same HardwareContext object (mutation)."""
    event = _make_event("nothing special")
    ctx = _make_ctx()
    result = analyse_waves(ctx, event)
    assert result is ctx


def test_derived_signals_json_serialisable():
    """All derived_signals values must be JSON-serialisable after wave analysis."""
    event = _make_event("amdgpu: ring gfx_0 timeout RING_HEAD=0x100 RING_TAIL=0x100 reset")
    ctx = _make_ctx(derived_signals={"cp_stalled": True, "mmhub_fault": True})
    result = analyse_waves(ctx, event)
    # Should not raise
    json.dumps(result.derived_signals)
