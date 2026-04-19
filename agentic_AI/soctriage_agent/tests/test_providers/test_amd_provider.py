"""Tests for AMDProvider — 30 tests covering all specified behaviors."""
from __future__ import annotations
import pathlib
import pytest
from soctriage.providers.amd.provider import AMDProvider

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "phase5"


@pytest.fixture(scope="module")
def provider() -> AMDProvider:
    return AMDProvider()


@pytest.fixture(scope="module")
def mi300_log() -> str:
    return (FIXTURES / "amd_mi300_mmhub_stall.log").read_text()


@pytest.fixture(scope="module")
def navi21_log() -> str:
    return (FIXTURES / "amd_navi21_gfx_hang.log").read_text()


@pytest.fixture(scope="module")
def psp_log() -> str:
    return (FIXTURES / "amd_psp_fw_fail.log").read_text()


# ---------------------------------------------------------------------------
# 1. name()
# ---------------------------------------------------------------------------

def test_name_returns_amd_rdna_cdna(provider):
    assert provider.name() == "AMD RDNA/CDNA"


# ---------------------------------------------------------------------------
# 2-4. detect()
# ---------------------------------------------------------------------------

def test_detect_returns_float(provider, mi300_log):
    result = provider.detect(mi300_log)
    assert isinstance(result, float)


def test_detect_float_in_range(provider, mi300_log):
    result = provider.detect(mi300_log)
    assert 0.0 <= result <= 1.0


def test_detect_above_threshold_on_mi300_log(provider, mi300_log):
    assert provider.detect(mi300_log) >= 0.5


def test_detect_returns_zero_on_nvidia_log(provider):
    nvidia_log = "nvidia NVRM XID 79: GPU-0 crashed Xid=79 TDR recovery failed"
    assert provider.detect(nvidia_log) == 0.0


# ---------------------------------------------------------------------------
# 5-6. classify_ip() edge cases
# ---------------------------------------------------------------------------

def test_classify_ip_empty_stream_returns_empty(provider):
    assert provider.classify_ip([]) == []


def test_classify_ip_unknown_token_type_returns_empty(provider):
    result = provider.classify_ip([{"type": "completely_unknown_type", "raw": "whatever"}])
    assert result == []


# ---------------------------------------------------------------------------
# 7-19. classify_ip() rule matching
# ---------------------------------------------------------------------------

def test_classify_ip_gpu_event_gfx(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "gfx ring hang"}])
    assert result[0]["ip"] == "GFX"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "gpu"


def test_classify_ip_gpu_event_sdma(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "sdma timeout"}])
    assert result[0]["ip"] == "SDMA"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "gpu"


def test_classify_ip_gpu_event_vcn(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "vcn encode hang"}])
    assert result[0]["ip"] == "VCN"
    assert result[0]["confidence"] == 0.90


def test_classify_ip_reset_event_gpu_reset(provider):
    result = provider.classify_ip([{"type": "reset_event", "raw": "GPU reset initiated"}])
    assert result[0]["ip"] == "GFX"
    assert result[0]["confidence"] == 0.85


def test_classify_ip_memory_event_vram(provider):
    result = provider.classify_ip([{"type": "memory_event", "raw": "VRAM corruption detected"}])
    assert result[0]["ip"] == "MMHUB"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "memory"


def test_classify_ip_memory_poison_hbm(provider):
    result = provider.classify_ip([{"type": "memory_poison", "raw": "HBM3 ECC uncorrectable"}])
    assert result[0]["ip"] == "GMC"
    assert result[0]["confidence"] == 0.95
    assert result[0]["subsystem"] == "memory"


def test_classify_ip_ras_event_ue(provider):
    result = provider.classify_ip([{"type": "ras_event", "raw": "RAS UE detected on SDMA"}])
    # "RAS" pattern matches first with conf=0.95, subsystem="debug"
    assert result[0]["ip"] == "RLC"
    assert result[0]["subsystem"] == "debug"


def test_classify_ip_ras_event_ue_only(provider):
    result = provider.classify_ip([{"type": "ras_event", "raw": "UE error at address 0x1234"}])
    assert result[0]["ip"] == "RLC"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "debug"


def test_classify_ip_amd_psp_fw_fail(provider):
    result = provider.classify_ip([{"type": "amd_psp_fw_fail", "raw": "PSP bootloader status: fault"}])
    assert result[0]["ip"] == "PSP"
    assert result[0]["confidence"] == 0.98
    assert result[0]["subsystem"] == "firmware"


def test_classify_ip_amd_psp_event_psp(provider):
    result = provider.classify_ip([{"type": "amd_psp_event", "raw": "PSP initialization"}])
    assert result[0]["ip"] == "PSP"
    assert result[0]["subsystem"] == "firmware"


def test_classify_ip_amd_sev_event(provider):
    result = provider.classify_ip([{"type": "amd_sev_event", "raw": "SEV-SNP attestation failed"}])
    assert result[0]["ip"] == "PSP"
    assert result[0]["confidence"] == 0.95
    assert result[0]["subsystem"] == "security"


def test_classify_ip_power_event_pmfw(provider):
    result = provider.classify_ip([{"type": "power_event", "raw": "PMFW voltage regulator fault"}])
    assert result[0]["ip"] == "SMU"
    assert result[0]["confidence"] == 0.88
    assert result[0]["subsystem"] == "power"


def test_classify_ip_thermal_event_tj_max(provider):
    result = provider.classify_ip([{"type": "thermal_event", "raw": "TJ_MAX exceeded threshold"}])
    assert result[0]["ip"] == "SMU"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "power"


def test_classify_ip_smmu_fault_amd_iommu(provider):
    result = provider.classify_ip([{"type": "smmu_fault", "raw": "AMD IOMMU fault on device"}])
    assert result[0]["ip"] == "IH"
    assert result[0]["confidence"] == 0.85


def test_classify_ip_display_event_dcn(provider):
    result = provider.classify_ip([{"type": "display_event", "raw": "DCN underrun detected"}])
    assert result[0]["ip"] == "DCN"


def test_classify_ip_result_has_all_keys(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "gfx hang"}])
    assert len(result) == 1
    entry = result[0]
    assert "ip" in entry
    assert "confidence" in entry
    assert "subsystem" in entry
    assert "notes" in entry


# ---------------------------------------------------------------------------
# 20-23. resolve_cascade()
# ---------------------------------------------------------------------------

def test_resolve_cascade_empty_returns_empty(provider):
    assert provider.resolve_cascade([]) == []


def test_resolve_cascade_psp_chain_starts_with_psp(provider):
    ip_hits = [
        {"ip": "PSP",  "confidence": 0.98},
        {"ip": "GFX",  "confidence": 0.75},
        {"ip": "SDMA", "confidence": 0.70},
    ]
    chain = provider.resolve_cascade(ip_hits)
    assert chain[0] == "PSP"
    assert "GFX" in chain


def test_resolve_cascade_returns_list_of_str(provider):
    ip_hits = [{"ip": "PSP", "confidence": 0.98}]
    chain = provider.resolve_cascade(ip_hits)
    assert isinstance(chain, list)
    assert all(isinstance(s, str) for s in chain)


def test_resolve_cascade_primary_is_highest_confidence(provider):
    ip_hits = [
        {"ip": "GMC", "confidence": 0.88},
        {"ip": "GFX", "confidence": 0.90},
    ]
    chain = provider.resolve_cascade(ip_hits)
    assert chain[0] == "GFX"


# ---------------------------------------------------------------------------
# 24-25. get_playbook()
# ---------------------------------------------------------------------------

def test_get_playbook_psp_has_steps_key(provider):
    playbook = provider.get_playbook("PSP")
    assert "steps" in playbook
    assert len(playbook["steps"]) > 0


def test_get_playbook_nonexistent_returns_empty(provider):
    assert provider.get_playbook("nonexistent_ip_block") == {}


# ---------------------------------------------------------------------------
# 26-27. get_register_maps() and decode_registers()
# ---------------------------------------------------------------------------

def test_get_register_maps_has_grbm_status(provider):
    reg_maps = provider.get_register_maps()
    assert isinstance(reg_maps, dict)
    assert "GRBM_STATUS" in reg_maps


def test_decode_registers_grbm_status_has_gui_active(provider):
    result = provider.decode_registers({"GRBM_STATUS": 0xC0000000})
    assert "GRBM_STATUS" in result
    assert "fields" in result["GRBM_STATUS"]
    assert result["GRBM_STATUS"]["fields"].get("GUI_ACTIVE") is True


# ---------------------------------------------------------------------------
# 28-29. get_known_issues()
# ---------------------------------------------------------------------------

def test_get_known_issues_cdna3_gpu_hang_includes_mi300_001(provider):
    issues = provider.get_known_issues("amd_cdna3", ["gpu_hang", "memory_event"])
    ids = [i["issue_id"] for i in issues]
    assert "AMD-MI300-001" in ids


def test_get_known_issues_rdna3_psp_fw_fail_includes_psp_001(provider):
    issues = provider.get_known_issues("amd_rdna3", ["amd_psp_fw_fail"])
    ids = [i["issue_id"] for i in issues]
    assert "AMD-PSP-001" in ids


# ---------------------------------------------------------------------------
# 30. get_hang_rules()
# ---------------------------------------------------------------------------

def test_get_hang_rules_returns_at_least_5(provider):
    from soctriage.core.soc_provider import HangRule
    rules = provider.get_hang_rules()
    assert len(rules) >= 5
    assert all(isinstance(r, HangRule) for r in rules)
