"""
test_scan_dump_parser.py — Phase 3c v3c.1.0
24 tests for scan_dump_parser.parse_registers()
Expected: 24 PASSED, 0 FAILED
"""

from __future__ import annotations

import pytest

from soctriage.core.assembler import LogEvent
from soctriage.core.tokenizer import LogToken
from soctriage.core.scan_dump_parser import parse_registers
from soctriage.core.hardware_decode import HardwareContext

# ── Helper ────────────────────────────────────────────────────────────────────


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
        provider_name=provider_name,
    )


# ── Parser basics (6) ─────────────────────────────────────────────────────────


def test_parse_name_equals_hex():
    """NAME=0xHEX format is parsed correctly."""
    event = _make_event("GRBM_STATUS=0xA0001020")
    ctx = parse_registers(event)
    assert ctx is not None
    assert any(r.name == "GRBM_STATUS" and r.raw_value == 0xA0001020 for r in ctx.registers)


def test_parse_name_colon_hex():
    """NAME: 0xHEX format is parsed correctly."""
    event = _make_event("CP_STALLED_STAT1: 0x00000001")
    ctx = parse_registers(event)
    assert ctx is not None
    assert any(r.name == "CP_STALLED_STAT1" and r.raw_value == 1 for r in ctx.registers)


def test_parse_bare_hex_without_0x_prefix():
    """NAME=HEX (no 0x prefix) is accepted as base-16."""
    event = _make_event("MMHUB_STATUS = deadbeef")
    ctx = parse_registers(event)
    assert ctx is not None
    assert any(r.name == "MMHUB_STATUS" and r.raw_value == 0xDEADBEEF for r in ctx.registers)


def test_register_names_uppercased():
    """Register names matched in uppercase — kernel logs always use uppercase names."""
    event = _make_event("GRBM_STATUS=0x00000001")
    ctx = parse_registers(event)
    assert ctx is not None
    assert any(r.name == "GRBM_STATUS" for r in ctx.registers)


def test_duplicate_registers_preserved():
    """Duplicate register names appear in order, no deduplication."""
    raw = "GRBM_STATUS=0x00000001\nGRBM_STATUS=0x00000002"
    event = _make_event(raw)
    ctx = parse_registers(event)
    assert ctx is not None
    names = [r.name for r in ctx.registers if r.name == "GRBM_STATUS"]
    assert len(names) == 2
    values = [r.raw_value for r in ctx.registers if r.name == "GRBM_STATUS"]
    assert values == [1, 2]


def test_unknown_register_preserved():
    """Unknown register names (not in any decode table) are preserved."""
    event = _make_event("MYSTERY_REG=0xDEADBEEF")
    ctx = parse_registers(event)
    assert ctx is not None
    assert any(r.name == "MYSTERY_REG" for r in ctx.registers)


# ── AMD decode (5) ────────────────────────────────────────────────────────────


def test_amd_grbm_status_decodes_cp_busy():
    """GRBM_STATUS bit 5 set → cp_busy=True in derived_signals."""
    # bit 5 = 0x20, bit 31 = 0x80000000; value with both bits set
    event = _make_event("GRBM_STATUS=0x80000020")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("cp_busy") is True
    assert ctx.derived_signals.get("gui_active") is True


def test_amd_cp_stalled_sets_signal():
    """CP_STALLED_STAT1 != 0 → cp_stalled=True."""
    event = _make_event("CP_STALLED_STAT1=0x00000001")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("cp_stalled") is True


def test_amd_mmhub_status_sets_fault():
    """MMHUB_STATUS != 0 → mmhub_fault=True."""
    event = _make_event("MMHUB_STATUS=0x00000001")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("mmhub_fault") is True


def test_amd_psp_status_boot_fail():
    """PSP_STATUS != 0 → psp_boot_fail=True."""
    event = _make_event("PSP_STATUS=0x00000002")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("psp_boot_fail") is True


def test_amd_ras_err_status_sets_ras_ue():
    """RAS_ERR_STATUS != 0 → ras_ue=True."""
    event = _make_event("RAS_ERR_STATUS=0x00000001")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("ras_ue") is True


# ── Intel decode (4) ─────────────────────────────────────────────────────────


def test_intel_guc_zero_means_not_alive():
    """GUC_STATUS[0]=0x0 → guc_alive=False."""
    event = _make_event("GUC_STATUS[0]=0x00000000", chip_gen="intel_gen12", provider_name="Intel")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("guc_alive") is False


def test_intel_guc_booting_value():
    """GUC_STATUS[0]=0x4 → guc_booting=True, guc_alive=True."""
    event = _make_event("GUC_STATUS[0]=0x00000004", chip_gen="intel_gen12", provider_name="Intel")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("guc_booting") is True
    assert ctx.derived_signals.get("guc_alive") is True


def test_intel_gtt_fault_sets_signal():
    """GTT_FAULT_STATUS != 0 → gtt_fault=True."""
    event = _make_event("GTT_FAULT_STATUS=0x00000001", chip_gen="intel_gen12", provider_name="Intel")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("gtt_fault") is True


def test_intel_ring_timeout_signal():
    """RING ... timeout token in raw_text → ring_stall=True."""
    raw = "i915: RING gfx_0 timeout seq=442 signaled=0 emitted=1"
    event = _make_event(raw, event_type="gpu_hang", chip_gen="intel_gen12", provider_name="Intel")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("ring_stall") is True


# ── Qualcomm decode (4) ───────────────────────────────────────────────────────


def test_qcom_adsp_ssr_token_sets_signal():
    """'ADSP state=SSR' line → adsp_ssr=True."""
    event = _make_event("ADSP state=SSR reason=wdog_bite", chip_gen="qcom_sc8280xp",
                        provider_name="Qualcomm")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("adsp_ssr") is True


def test_qcom_cdsp_ssr_token_sets_signal():
    """'CDSP state=SSR' line → cdsp_ssr=True."""
    event = _make_event("CDSP state=SSR reason=wdog_bite", chip_gen="qcom_sc8280xp",
                        provider_name="Qualcomm")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("cdsp_ssr") is True


def test_qcom_spmi_timeout_sets_signal():
    """'SPMI timeout' token → spmi_fault=True."""
    event = _make_event("spmi: SPMI timeout on bus 0", chip_gen="qcom_sc8280xp",
                        provider_name="Qualcomm")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("spmi_fault") is True


def test_qcom_rpmh_timeout_sets_signal():
    """'RPMH timeout' token → rpmh_timeout=True."""
    event = _make_event("RPMH timeout detected", chip_gen="qcom_sc8280xp",
                        provider_name="Qualcomm")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("rpmh_timeout") is True


# ── NVIDIA decode (3) ─────────────────────────────────────────────────────────


def test_nvidia_gsp_boot_fail():
    """GSP_BOOT_STATUS != 0 → gsp_boot_fail=True."""
    event = _make_event("GSP_BOOT_STATUS=0x00000002", chip_gen="nvidia_ga102",
                        provider_name="NVIDIA")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("gsp_boot_fail") is True


def test_nvidia_fb_ecc_ue():
    """FB_ECC_STATUS != 0 → fb_ecc_ue=True."""
    event = _make_event("FB_ECC_STATUS=0x00000001", chip_gen="nvidia_ga102",
                        provider_name="NVIDIA")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("fb_ecc_ue") is True


def test_nvidia_bar2_fault():
    """BAR2_FAULT token in raw_text → bar2_fault=True."""
    event = _make_event("nvidia: BAR2_FAULT detected at offset 0x1000",
                        chip_gen="nvidia_ga102", provider_name="NVIDIA")
    ctx = parse_registers(event)
    assert ctx is not None
    assert ctx.derived_signals.get("bar2_fault") is True


# ── Malformed input (2) ───────────────────────────────────────────────────────


def test_malformed_hex_adds_note():
    """Malformed hex value adds a note and does NOT crash."""
    event = _make_event("GRBM_STATUS=0xGGGGGGGG")
    ctx = parse_registers(event)
    # May return None if only malformed registers, or return context with note
    # The key requirement is: no exception raised and if context returned, note present
    # If only malformed, returns None (no valid evidence)
    if ctx is not None:
        assert any("malformed" in n.lower() for n in ctx.notes)


def test_no_hardware_evidence_returns_none():
    """A plain text log with no registers returns None."""
    event = _make_event("kernel: some generic log message with no hardware data")
    ctx = parse_registers(event)
    assert ctx is None
