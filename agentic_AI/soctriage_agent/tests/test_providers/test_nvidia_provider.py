"""20 tests for NVIDIAProvider — Phase 5."""
from __future__ import annotations
import pathlib
import pytest
from soctriage.providers.nvidia.provider import NVIDIAProvider
from soctriage.core.soc_provider import HangRule

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "phase5"


@pytest.fixture(scope="module")
def provider() -> NVIDIAProvider:
    return NVIDIAProvider()


@pytest.fixture(scope="module")
def h100_log() -> str:
    return (FIXTURE_DIR / "nvidia_h100_gsp_timeout.log").read_text()


# ── 1. name() ──────────────────────────────────────────────────────────────
def test_name(provider):
    assert provider.name() == "NVIDIA GPU"


# ── 2. detect() returns float in [0.0, 1.0] ────────────────────────────────
def test_detect_range(provider, h100_log):
    score = provider.detect(h100_log)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


# ── 3. detect() >= 0.5 on NVIDIA H100 GSP timeout log ─────────────────────
def test_detect_nvidia_log(provider, h100_log):
    assert provider.detect(h100_log) >= 0.5


# ── 4. detect() returns 0.0 on qcom-only log ──────────────────────────────
def test_detect_qcom_zero(provider):
    score = provider.detect("qcom msm adreno kgsl")
    assert score == 0.0


# ── 5. classify_ip([]) = [] ────────────────────────────────────────────────
def test_classify_empty(provider):
    assert provider.classify_ip([]) == []


# ── 6. classify_ip with unknown type returns [] ────────────────────────────
def test_classify_unknown_type(provider):
    result = provider.classify_ip([{"type": "unknown_xyz", "raw": "something"}])
    assert result == []


# ── 7. gpu_event + "gr" → GPC, conf=0.88, subsystem="gpu" ─────────────────
def test_classify_gpu_event_gr(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "gr engine hang"}])
    assert len(result) == 1
    assert result[0]["ip"] == "GPC"
    assert result[0]["confidence"] == 0.88
    assert result[0]["subsystem"] == "gpu"


# ── 8. gpu_event + "GPC" → GPC ────────────────────────────────────────────
def test_classify_gpu_event_gpc(provider):
    result = provider.classify_ip([{"type": "gpu_event", "raw": "GPC fault detected"}])
    assert result[0]["ip"] == "GPC"


# ── 9. reset_event + "GPU reset" → GPC, conf=0.85 ─────────────────────────
def test_classify_reset_event(provider):
    result = provider.classify_ip([{"type": "reset_event", "raw": "GPU reset triggered"}])
    assert result[0]["ip"] == "GPC"
    assert result[0]["confidence"] == 0.85


# ── 10. firmware_event + "GSP" → GSP, conf=0.95, subsystem="firmware" ─────
def test_classify_firmware_gsp(provider):
    result = provider.classify_ip([{"type": "firmware_event", "raw": "GSP RPC timeout"}])
    assert result[0]["ip"] == "GSP"
    assert result[0]["confidence"] == 0.95
    assert result[0]["subsystem"] == "firmware"


# ── 11. pcie_error + "nvidia" → PCIe, conf=0.85, subsystem="interconnect" ─
def test_classify_pcie_nvidia(provider):
    result = provider.classify_ip([{"type": "pcie_error", "raw": "nvidia PCIe link down"}])
    assert result[0]["ip"] == "PCIe"
    assert result[0]["confidence"] == 0.85
    assert result[0]["subsystem"] == "interconnect"


# ── 12. memory_event + "FBPA" → FBPA, conf=0.90, subsystem="memory" ───────
def test_classify_memory_fbpa(provider):
    result = provider.classify_ip([{"type": "memory_event", "raw": "FBPA ECC error"}])
    assert result[0]["ip"] == "FBPA"
    assert result[0]["confidence"] == 0.90
    assert result[0]["subsystem"] == "memory"


# ── 13. display_event + "DISP" → DISPLAY ──────────────────────────────────
def test_classify_display_disp(provider):
    result = provider.classify_ip([{"type": "display_event", "raw": "DISP engine hang"}])
    assert result[0]["ip"] == "DISPLAY"


# ── 14. power_event + "PMU" → PMU, subsystem="power" ─────────────────────
def test_classify_power_pmu(provider):
    result = provider.classify_ip([{"type": "power_event", "raw": "PMU fault detected"}])
    assert result[0]["ip"] == "PMU"
    assert result[0]["subsystem"] == "power"


# ── 15. classify_ip result has all 4 required keys ────────────────────────
def test_classify_result_keys(provider):
    result = provider.classify_ip([{"type": "firmware_event", "raw": "GSP timeout"}])
    assert len(result) == 1
    hit = result[0]
    for key in ("ip", "confidence", "subsystem", "notes"):
        assert key in hit, f"missing key: {key}"


# ── 16. resolve_cascade([]) = [] ──────────────────────────────────────────
def test_resolve_cascade_empty(provider):
    assert provider.resolve_cascade([]) == []


# ── 17. resolve_cascade(GSP hit) → chain starts with GSP, includes GPC ────
def test_resolve_cascade_gsp(provider):
    hits = [
        {"ip": "GSP", "confidence": 0.95},
        {"ip": "GPC", "confidence": 0.88},
    ]
    chain = provider.resolve_cascade(hits)
    assert chain[0] == "GSP"
    assert "GPC" in chain


# ── 18. get_playbook("GSP") has "steps" key; get_playbook("X") = {} ────────
def test_get_playbook(provider):
    pb = provider.get_playbook("GSP")
    assert "steps" in pb
    assert isinstance(pb["steps"], list)
    assert provider.get_playbook("X") == {}


# ── 19. get_known_issues("nvidia_hopper", ["firmware_event"]) includes NV-HOPPER-001 ─
def test_get_known_issues_hopper_firmware(provider):
    issues = provider.get_known_issues("nvidia_hopper", ["firmware_event"])
    ids = [i["issue_id"] for i in issues]
    assert "NV-HOPPER-001" in ids


# ── 20. get_hang_rules() returns >= 4 HangRule objects ────────────────────
def test_get_hang_rules(provider):
    rules = provider.get_hang_rules()
    assert len(rules) >= 4
    assert all(isinstance(r, HangRule) for r in rules)
