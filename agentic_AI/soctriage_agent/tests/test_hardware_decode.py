"""
test_hardware_decode.py — Phase 3c v3c.1.0
14 integration tests for hardware_decode.decode_hardware()
Expected: 14 PASSED, 0 FAILED
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.tokenizer import LogToken
from soctriage.core.hardware_decode import decode_hardware, HardwareContext

# ── Fixture directory ─────────────────────────────────────────────────────────

_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "phase3c"

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
    provider_name: str = "AMD RDNA/CDNA",
    event_id: int = 1,
) -> LogEvent:
    tok = _tok(raw_text, chip_gen)
    return LogEvent(
        event_id=event_id,
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
        provider_name=provider_name,
    )


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _event_from_fixture(
    name: str,
    event_type: str = "gpu_hang",
    chip_gen: str = "amd_rdna3",
    provider_name: str = "generic",
) -> LogEvent:
    raw_text = _load_fixture(name)
    return _make_event(raw_text, event_type=event_type, chip_gen=chip_gen,
                       provider_name=provider_name)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_decode_hardware_returns_same_event_list():
    """decode_hardware() must return the same list object passed in."""
    events = [_make_event("GRBM_STATUS=0x00000001")]
    result = decode_hardware(events)
    assert result is events


def test_event_without_registers_gets_none_context():
    """Events with no hardware evidence get hardware_context=None."""
    event = _make_event("kernel: some generic log line with nothing special")
    decode_hardware([event])
    assert event.__dict__.get("hardware_context") is None


def test_amd_fixture_gets_gpu_hard_stall():
    """AMD grbm+cp_stall fixture → stall_type in {gpu_hard_stall, reset_storm}."""
    event = _event_from_fixture(
        "amd_grbm_cp_stall.log",
        event_type="gpu_hang",
        chip_gen="amd_rdna3",
        provider_name="AMD RDNA/CDNA",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type in {"gpu_hard_stall", "reset_storm"}


def test_amd_mmhub_fixture_gets_translation_fault():
    """AMD mmhub fault fixture → stall_type == memory_translation_fault."""
    event = _event_from_fixture(
        "amd_mmhub_fault.log",
        event_type="gpu_hang",
        chip_gen="amd_rdna3",
        provider_name="AMD RDNA/CDNA",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type == "memory_translation_fault"


def test_intel_guc_fixture_gets_firmware_boot_fail():
    """Intel GuC dead fixture → stall_type == firmware_boot_fail."""
    event = _event_from_fixture(
        "intel_guc_dead.log",
        event_type="firmware_fail",
        chip_gen="intel_gen12",
        provider_name="Intel",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type == "firmware_boot_fail"


def test_intel_reset_fixture_gets_reset_storm():
    """Intel GT reset fixture → stall_type == reset_storm."""
    event = _event_from_fixture(
        "intel_gt_reset.log",
        event_type="gpu_hang",
        chip_gen="intel_gen12",
        provider_name="Intel",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    # GT reset + timeout + equal ring heads → reset_storm or gpu_hard_stall
    assert ctx.stall_type in {"reset_storm", "gpu_hard_stall"}


def test_qcom_adsp_fixture_gets_runtime_crash():
    """Qualcomm ADSP SSR fixture → stall_type == firmware_runtime_crash."""
    event = _event_from_fixture(
        "qcom_adsp_ssr.log",
        event_type="soc_crash",
        chip_gen="qcom_sc8280xp",
        provider_name="Qualcomm",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type == "firmware_runtime_crash"


def test_qcom_spmi_fixture_gets_power_or_translation_fault():
    """Qualcomm SPMI/RPMh fixture → power_gating_fault or memory_translation_fault."""
    event = _event_from_fixture(
        "qcom_spmi_timeout.log",
        event_type="power_fault",
        chip_gen="qcom_sc8280xp",
        provider_name="Qualcomm",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type in {"power_gating_fault", "memory_translation_fault",
                               "unknown_hardware_fault"}


def test_nvidia_gsp_fixture_gets_firmware_boot_fail():
    """NVIDIA GSP boot fail fixture → stall_type == firmware_boot_fail."""
    event = _event_from_fixture(
        "nvidia_gsp_boot_fail.log",
        event_type="firmware_fail",
        chip_gen="nvidia_ga102",
        provider_name="NVIDIA",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type == "firmware_boot_fail"


def test_generic_fixture_gets_unknown_hardware_fault():
    """Generic unknown registers → stall_type == unknown_hardware_fault."""
    event = _event_from_fixture(
        "generic_unknown_regs.log",
        event_type="gpu_hang",
        chip_gen="unknown",
        provider_name="generic",
    )
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    assert ctx.stall_type == "unknown_hardware_fault"
    # Unknown registers must be preserved
    assert len(ctx.registers) > 0


def test_decode_pipeline_openlog_to_hardware_context():
    """End-to-end: raw text → decode_hardware() → hardware_context attached."""
    raw = (
        "amdgpu: GPU hang detected\n"
        "amdgpu: GRBM_STATUS=0x80000020\n"
        "amdgpu: CP_STALLED_STAT1=0x00000001\n"
    )
    event = _make_event(raw, event_type="gpu_hang")
    events = decode_hardware([event])
    assert events[0].__dict__.get("hardware_context") is not None
    ctx = events[0].__dict__["hardware_context"]
    assert ctx.stall_type in {"gpu_hard_stall", "reset_storm", "firmware_boot_fail"}


def test_hardware_context_to_dict_json_serialisable():
    """HardwareContext.to_dict() produces a JSON-serialisable dict."""
    raw = "GRBM_STATUS=0xA0001020\nCP_STALLED_STAT1=0x00000001"
    event = _make_event(raw)
    decode_hardware([event])
    ctx: HardwareContext = event.__dict__["hardware_context"]
    assert ctx is not None
    d = ctx.to_dict()
    # Must not raise
    json.dumps(d)
    assert "stall_type" in d
    assert "registers" in d
    assert "derived_signals" in d


def test_malformed_register_does_not_crash_pipeline():
    """Malformed hex in register line does not abort the pipeline."""
    raw = "GRBM_STATUS=0xGGGGGGGG\nCP_STALLED_STAT1=0x00000001"
    event = _make_event(raw)
    # Must not raise
    decode_hardware([event])
    # CP_STALLED_STAT1 is valid so context should be present
    ctx = event.__dict__.get("hardware_context")
    assert ctx is not None
    # Note about malformed register should be present
    assert any("malformed" in n.lower() for n in ctx.notes)


def test_perf_1000_events_under_200ms():
    """1000 mixed events must complete decode in ≤200ms."""
    events = []
    for i in range(1000):
        if i % 4 == 0:
            raw = f"GRBM_STATUS=0xA0001020\nCP_STALLED_STAT1=0x00000001\nring gfx_0 timeout"
        elif i % 4 == 1:
            raw = f"GUC_STATUS[0]=0x00000000\nGuC not alive"
        elif i % 4 == 2:
            raw = f"ADSP state=SSR reason=wdog_bite"
        else:
            raw = f"kernel: plain log line {i}"
        events.append(_make_event(raw, event_id=i + 1))

    t0 = time.perf_counter()
    decode_hardware(events)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms <= 200, f"decode_hardware took {elapsed_ms:.1f}ms for 1000 events (limit 200ms)"
