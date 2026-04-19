"""Tests for IntelProvider — 28 tests covering all public methods."""
from __future__ import annotations

import pathlib
import pytest

from soctriage.providers.intel.provider import IntelProvider
from soctriage.core.soc_provider import HangRule

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "phase5"


@pytest.fixture
def provider() -> IntelProvider:
    return IntelProvider()


@pytest.fixture
def dg2_log() -> str:
    return (FIXTURES / "intel_dg2_guc_hang.log").read_text()


@pytest.fixture
def pvc_log() -> str:
    return (FIXTURES / "intel_pvc_sriov_reset.log").read_text()


@pytest.fixture
def mtl_log() -> str:
    return (FIXTURES / "intel_mtl_tbt_smmu.log").read_text()


# ── name ──────────────────────────────────────────────────────────────────────

def test_name(provider):
    assert provider.name() == "Intel Xe/Gen Graphics"


# ── detect ────────────────────────────────────────────────────────────────────

def test_detect_dg2_guc_hang_returns_high_confidence(provider, dg2_log):
    score = provider.detect(dg2_log)
    assert score >= 0.5

def test_detect_amd_log_returns_zero(provider):
    amd_log = "amdgpu GRBM_STATUS: something went wrong in GRBM"
    assert provider.detect(amd_log) == pytest.approx(0.0)

def test_detect_pvc_log_returns_high_confidence(provider, pvc_log):
    score = provider.detect(pvc_log)
    assert score >= 0.5

def test_detect_mtl_log_returns_high_confidence(provider, mtl_log):
    score = provider.detect(mtl_log)
    assert score >= 0.5

def test_detect_caps_at_1_0(provider):
    # Log with many keywords should not exceed 1.0
    heavy = " ".join(["i915", "xe driver", "drm/i915", "GuC", "HuC",
                       "intel_iommu", "thunderbolt", "usb4", "GEN12",
                       "Xe HP", "DG2", "Flex Series", "Meteor Lake"] * 3)
    assert provider.detect(heavy) <= 1.0

def test_detect_empty_log_returns_zero(provider):
    assert provider.detect("") == pytest.approx(0.0)


# ── classify_ip ───────────────────────────────────────────────────────────────

def test_classify_ip_firmware_guc(provider):
    tokens = [{"type": "firmware_event", "raw": "GuC firmware load failed"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "GUC" in ips

def test_classify_ip_firmware_huc(provider):
    tokens = [{"type": "firmware_event", "raw": "HuC firmware auth failed"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "HUC" in ips

def test_classify_ip_firmware_gsc(provider):
    tokens = [{"type": "firmware_event", "raw": "GSC init failed"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "GSC" in ips

def test_classify_ip_gpu_rcs0(provider):
    tokens = [{"type": "gpu_event", "raw": "engine rcs0 hang"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "RENDER" in ips

def test_classify_ip_gpu_bcs0(provider):
    tokens = [{"type": "gpu_event", "raw": "engine bcs0 reset"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "BLITTER" in ips

def test_classify_ip_gpu_vcs0(provider):
    tokens = [{"type": "gpu_event", "raw": "engine vcs0 timeout"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "MEDIA" in ips

def test_classify_ip_reset_gpu_hang(provider):
    tokens = [{"type": "reset_event", "raw": "GPU HANG: ecode 12:1"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "RENDER" in ips

def test_classify_ip_intel_gtt_event(provider):
    tokens = [{"type": "intel_gtt_event", "raw": "GGTT mapping fault"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "GGTT" in ips

def test_classify_ip_smmu_fault(provider):
    tokens = [{"type": "smmu_fault", "raw": "intel_iommu context fault"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "GGTT" in ips

def test_classify_ip_display_event_crtc(provider):
    tokens = [{"type": "display_event", "raw": "CRTC underrun on pipe A"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "DISPLAY" in ips

def test_classify_ip_pcie_error(provider):
    tokens = [{"type": "pcie_error", "raw": "i915: AER error on PCIe"}]
    results = provider.classify_ip(tokens)
    ips = [r["ip"] for r in results]
    assert "PCIe" in ips

def test_classify_ip_no_duplicates(provider):
    tokens = [
        {"type": "firmware_event", "raw": "GuC failed"},
        {"type": "firmware_event", "raw": "GuC failed again"},
    ]
    results = provider.classify_ip(tokens)
    guc_hits = [r for r in results if r["ip"] == "GUC"]
    assert len(guc_hits) == 1

def test_classify_ip_empty_stream(provider):
    assert provider.classify_ip([]) == []

def test_classify_ip_result_has_required_keys(provider):
    tokens = [{"type": "firmware_event", "raw": "GuC load failed"}]
    results = provider.classify_ip(tokens)
    assert len(results) >= 1
    for r in results:
        assert "ip" in r
        assert "confidence" in r
        assert "subsystem" in r


# ── resolve_cascade ───────────────────────────────────────────────────────────

def test_resolve_cascade_guc_includes_render(provider):
    ip_hits = [
        {"ip": "GUC", "confidence": 0.95},
        {"ip": "RENDER", "confidence": 0.90},
    ]
    chain = provider.resolve_cascade(ip_hits)
    assert "RENDER" in chain

def test_resolve_cascade_primary_is_highest_confidence(provider):
    ip_hits = [
        {"ip": "RENDER", "confidence": 0.90},
        {"ip": "GUC", "confidence": 0.95},
    ]
    chain = provider.resolve_cascade(ip_hits)
    assert chain[0] == "GUC"

def test_resolve_cascade_empty_returns_empty(provider):
    assert provider.resolve_cascade([]) == []


# ── get_playbook ──────────────────────────────────────────────────────────────

def test_get_playbook_guc_has_steps(provider):
    pb = provider.get_playbook("GUC")
    assert "steps" in pb
    assert len(pb["steps"]) > 0

def test_get_playbook_unknown_block_returns_empty_dict(provider):
    assert provider.get_playbook("NONEXISTENT") == {}


# ── decode_registers ──────────────────────────────────────────────────────────

def test_decode_registers_has_fields_key(provider):
    result = provider.decode_registers({"GUC_STATUS": 0x3})
    assert "fields" in result["GUC_STATUS"]

def test_decode_registers_guc_ready_bit_set(provider):
    result = provider.decode_registers({"GUC_STATUS": 0x1})
    assert result["GUC_STATUS"]["fields"]["GUC_READY"] is True

def test_decode_registers_unknown_register_returns_empty_fields(provider):
    result = provider.decode_registers({"UNKNOWN_REG": 0xDEADBEEF})
    assert result["UNKNOWN_REG"]["fields"] == {}


# ── get_hang_rules ────────────────────────────────────────────────────────────

def test_get_hang_rules_returns_at_least_4(provider):
    rules = provider.get_hang_rules()
    assert len(rules) >= 4

def test_get_hang_rules_are_hang_rule_instances(provider):
    rules = provider.get_hang_rules()
    for rule in rules:
        assert isinstance(rule, HangRule)


# ── get_known_issues ──────────────────────────────────────────────────────────

def test_get_known_issues_dg2_firmware_includes_dg2_001(provider):
    issues = provider.get_known_issues("intel_dg2", ["firmware_event"])
    ids = [i["issue_id"] for i in issues]
    assert "INTEL-DG2-001" in ids

def test_get_known_issues_wrong_chip_gen_returns_empty(provider):
    issues = provider.get_known_issues("nvidia_h100", ["gpu_hang"])
    assert issues == []

def test_get_known_issues_no_event_filter_returns_all_for_chip(provider):
    issues = provider.get_known_issues("intel_dg2")
    assert len(issues) >= 1
    for issue in issues:
        assert "intel_dg2" in issue["chip_gens"]
