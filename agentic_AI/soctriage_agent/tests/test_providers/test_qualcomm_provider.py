"""30 tests for QualcommProvider — Phase 5."""
from __future__ import annotations
import pathlib
import pytest
from soctriage.core.soc_provider import SoCProvider, HangRule
from soctriage.providers.qualcomm.provider import QualcommProvider

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "phase5"
SM8550_LOG = (FIXTURES / "qcom_sm8550_adsp_suspend.log").read_text()
SDM845_LOG = (FIXTURES / "qcom_sdm845_ufs_phy.log").read_text()
INTEL_ONLY_LOG = "i915 drm/i915 GuC firmware failed Intel Xe HP DG2 intel_iommu"


@pytest.fixture
def provider() -> QualcommProvider:
    return QualcommProvider()


# ── name() ────────────────────────────────────────────────────────────────────

def test_name_returns_string(provider):
    assert isinstance(provider.name(), str)


def test_name_contains_qualcomm(provider):
    assert "Qualcomm" in provider.name()


# ── detect() ──────────────────────────────────────────────────────────────────

def test_detect_returns_float(provider):
    score = provider.detect("some random log text")
    assert isinstance(score, float)


def test_detect_in_range(provider):
    score = provider.detect("qcom msm adreno kgsl llcc")
    assert 0.0 <= score <= 1.0


def test_detect_sm8550_fixture_high(provider):
    score = provider.detect(SM8550_LOG)
    assert score >= 0.5


def test_detect_intel_only_log_zero(provider):
    score = provider.detect(INTEL_ONLY_LOG)
    assert score == 0.0


def test_detect_empty_string_zero(provider):
    score = provider.detect("")
    assert score == 0.0


# ── classify_ip() ─────────────────────────────────────────────────────────────

def test_classify_ip_empty_stream(provider):
    assert provider.classify_ip([]) == []


def test_classify_ip_unknown_type_empty(provider):
    result = provider.classify_ip([{"type": "unknown_xyz", "raw": "whatever"}])
    assert result == []


def test_classify_ip_gpu_event_kgsl_adreno(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "kgsl hang detected"}])
    assert result[0]["ip"] == "ADRENO"


def test_classify_ip_qcom_adsp_crash_lpass(provider):
    result = provider.classify_ip([{"type": "qcom_adsp_crash", "raw": "ADSP subsystem crashed"}])
    assert result[0]["ip"] == "LPASS"


def test_classify_ip_qcom_cdsp_crash_wcss(provider):
    result = provider.classify_ip([{"type": "qcom_cdsp_crash", "raw": "CDSP crash"}])
    assert result[0]["ip"] == "WCSS"


def test_classify_ip_smmu_fault_arm_smmu(provider):
    result = provider.classify_ip([{"type": "smmu_fault", "raw": "arm-smmu context fault"}])
    assert result[0]["ip"] == "SMMU"


def test_classify_ip_ufs_event_ufshcd(provider):
    result = provider.classify_ip([{"type": "ufs_event", "raw": "ufshcd link down"}])
    assert result[0]["ip"] == "UFS"


def test_classify_ip_spmi_event_pm8_pmic(provider):
    result = provider.classify_ip([{"type": "spmi_event", "raw": "PM8998 timeout"}])
    assert result[0]["ip"] == "PMIC"


def test_classify_ip_remoteproc_crash_qcom_q6v5_lpass(provider):
    result = provider.classify_ip([{"type": "remoteproc_crash", "raw": "qcom_q6v5 crash"}])
    assert result[0]["ip"] == "LPASS"


def test_classify_ip_pcie_error_pcie(provider):
    result = provider.classify_ip([{"type": "pcie_error", "raw": "PCIe link down"}])
    assert result[0]["ip"] == "PCIe"


def test_classify_ip_display_event_mdss_camss(provider):
    result = provider.classify_ip([{"type": "display_event", "raw": "mdss dsi error"}])
    assert result[0]["ip"] == "CAMSS"


def test_classify_ip_wdt_event_cpuss(provider):
    result = provider.classify_ip([{"type": "wdt_event", "raw": "apps watchdog timeout"}])
    assert result[0]["ip"] == "CPUss"


def test_classify_ip_result_has_required_keys(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "kgsl hang"}])
    assert len(result) == 1
    entry = result[0]
    for key in ("ip", "confidence", "subsystem", "notes"):
        assert key in entry, f"missing key: {key}"


# ── resolve_cascade() ─────────────────────────────────────────────────────────

def test_resolve_cascade_empty(provider):
    assert provider.resolve_cascade([]) == []


def test_resolve_cascade_lpass_includes_cpuss(provider):
    hits = [
        {"ip": "LPASS",  "confidence": 0.98},
        {"ip": "CPUss",  "confidence": 0.80},
    ]
    chain = provider.resolve_cascade(hits)
    assert "LPASS" in chain
    assert "CPUss" in chain


def test_resolve_cascade_returns_list_of_str(provider):
    hits = [{"ip": "SMMU", "confidence": 0.90}]
    chain = provider.resolve_cascade(hits)
    assert isinstance(chain, list)
    assert all(isinstance(x, str) for x in chain)


# ── get_playbook() ────────────────────────────────────────────────────────────

def test_get_playbook_smmu_has_steps(provider):
    pb = provider.get_playbook("SMMU")
    assert "steps" in pb
    assert len(pb["steps"]) > 0


def test_get_playbook_nonexistent_returns_empty(provider):
    assert provider.get_playbook("NONEXISTENT_IP") == {}


# ── get_register_maps() ───────────────────────────────────────────────────────

def test_get_register_maps_nonempty(provider):
    rm = provider.get_register_maps()
    assert isinstance(rm, dict)
    assert len(rm) > 0


def test_get_register_maps_has_smmu_fsr(provider):
    rm = provider.get_register_maps()
    assert "SMMU_FSR" in rm


# ── decode_registers() ────────────────────────────────────────────────────────

def test_decode_registers_smmu_fsr_has_fields(provider):
    result = provider.decode_registers({"SMMU_FSR": 0x80000002})
    assert "SMMU_FSR" in result
    assert "fields" in result["SMMU_FSR"]


def test_decode_registers_unknown_reg_no_raise(provider):
    result = provider.decode_registers({"UNKNOWN_REG": 0xFF})
    assert "UNKNOWN_REG" in result


# ── get_known_issues() ────────────────────────────────────────────────────────

def test_get_known_issues_sm8550_adsp_crash(provider):
    issues = provider.get_known_issues("qcom_sm8550", ["qcom_adsp_crash"])
    ids = [i["issue_id"] for i in issues]
    assert "QCOM-ADSP-001" in ids


def test_get_known_issues_sdm845_phy_calibration(provider):
    issues = provider.get_known_issues("qcom_sdm845", ["phy_calibration_fail"])
    ids = [i["issue_id"] for i in issues]
    assert "QCOM-UFS-001" in ids


def test_get_known_issues_unknown_chip_empty(provider):
    assert provider.get_known_issues("unknown_chip", []) == []


# ── get_hang_rules() ─────────────────────────────────────────────────────────

def test_get_hang_rules_returns_at_least_4(provider):
    rules = provider.get_hang_rules()
    assert len(rules) >= 4


def test_get_hang_rules_are_hang_rule_instances(provider):
    rules = provider.get_hang_rules()
    assert all(isinstance(r, HangRule) for r in rules)


# ── isinstance SoCProvider ────────────────────────────────────────────────────

def test_qualcomm_provider_is_soc_provider(provider):
    assert isinstance(provider, SoCProvider)
