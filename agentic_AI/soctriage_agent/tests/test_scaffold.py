"""
Phase 0 Acceptance Tests — SoCTriage
Expected: 20 PASSED, 6 XFAIL, 0 FAILED, 0 ERROR
"""

import inspect
import os
import subprocess
import sys
import yaml
import pytest
from pathlib import Path

FIXTURES = Path("tests/fixtures")

AMD_FIXTURES = [
    "amd/gpu_hang_gfx.log", "amd/gpu_hang_sdma.log", "amd/gmc_vm_fault.log",
    "amd/psp_fw_fail.log", "amd/kasan_uaf.log", "amd/oom_killer.log",
    "amd/pcie_aer.log", "amd/arm64_panic.log", "amd/cdna_compute.log",
    "amd/ih_overflow.log", "amd/multi_gpu.log",
]
INTEL_FIXTURES = [
    "intel/guc_hang.log", "intel/huc_load_fail.log", "intel/gt_reset.log",
    "intel/lmem_fault.log", "intel/tbt_phy_error.log", "intel/usb4_link_down.log",
    "intel/intel_iommu_fault.log", "intel/pcie_aer_corrected.log",
]
QUALCOMM_FIXTURES = [
    "qualcomm/adreno_hang.log", "qualcomm/smmu_fault.log", "qualcomm/dwc3_usb_error.log",
    "qualcomm/llcc_error.log", "qualcomm/venus_timeout.log", "qualcomm/arm64_qcom_panic.log",
]
HW_FIXTURES = [
    "hw_domain/grbm_status_dump.log", "hw_domain/umr_wave_dump.log",
    "hw_domain/cp_stall.log", "hw_domain/sq_wave_mem_viol.log",
    "hw_domain/ecc_ras_event.log", "hw_domain/xgmi_fabric_error.log",
    "hw_domain/cache_tcc_error.log", "hw_domain/dcn_display_error.log",
]
GENERIC_FIXTURES = [
    "generic/normal_dmesg.log", "generic/empty.log",
    "generic/binary_contaminated.log", "generic/multi_event.log",
]
ALL_FIXTURES = AMD_FIXTURES + INTEL_FIXTURES + QUALCOMM_FIXTURES + HW_FIXTURES + GENERIC_FIXTURES


# ── AC-P0-01: Package importable ──────────────────────────────────────────────
def test_package_importable():
    import soctriage
    assert soctriage is not None


# ── AC-P0-02: SoCProvider importable ─────────────────────────────────────────
def test_soc_provider_importable():
    from soctriage.core.soc_provider import SoCProvider
    assert SoCProvider is not None


# ── AC-P0-03: Exactly 8 abstract methods ─────────────────────────────────────
def test_soc_provider_has_8_abstract_methods():
    from soctriage.core.soc_provider import SoCProvider
    abstract_methods = {
        name for name in dir(SoCProvider)
        if getattr(getattr(SoCProvider, name, None), "__isabstractmethod__", False)
    }
    assert len(abstract_methods) == 8, f"Found: {abstract_methods}"


# ── AC-P0-04: All providers are SoCProvider subclasses ───────────────────────
@pytest.mark.parametrize("module_path,class_name", [
    ("soctriage.providers.intel.provider",    "IntelProvider"),
    ("soctriage.providers.qualcomm.provider", "QualcommProvider"),
    ("soctriage.providers.amd.provider",      "AMDProvider"),
    ("soctriage.providers.nvidia.provider",   "NVIDIAProvider"),
    ("soctriage.providers.generic.provider",  "GenericProvider"),
])
def test_provider_is_subclass(module_path, class_name):
    import importlib
    from soctriage.core.soc_provider import SoCProvider
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    assert issubclass(cls, SoCProvider)


# ── AC-P0-05: All providers instantiable ─────────────────────────────────────
def test_intel_provider_name():
    from soctriage.providers.intel.provider import IntelProvider
    assert IntelProvider().name() == "Intel Xe/Gen Graphics"

def test_qualcomm_provider_name():
    from soctriage.providers.qualcomm.provider import QualcommProvider
    assert QualcommProvider().name() == "Qualcomm MSM/Snapdragon"

def test_amd_provider_name():
    from soctriage.providers.amd.provider import AMDProvider
    assert AMDProvider().name() == "AMD RDNA/CDNA"

def test_nvidia_provider_name():
    from soctriage.providers.nvidia.provider import NVIDIAProvider
    assert NVIDIAProvider().name() == "NVIDIA GPU"

def test_generic_provider_fallback_confidence():
    from soctriage.providers.generic.provider import GenericProvider
    assert GenericProvider().detect("anything") == 0.1


# ── AC-P0-06: IP block counts ────────────────────────────────────────────────
def test_intel_ip_blocks():
    from soctriage.providers.intel.ip_definitions import INTEL_IP_BLOCKS
    assert len(INTEL_IP_BLOCKS) == 15

def test_qualcomm_ip_blocks():
    from soctriage.providers.qualcomm.ip_definitions import QUALCOMM_IP_BLOCKS
    assert len(QUALCOMM_IP_BLOCKS) == 15

def test_amd_ip_blocks():
    from soctriage.providers.amd.ip_definitions import AMD_IP_BLOCKS
    assert len(AMD_IP_BLOCKS) == 14
    required = {"GFX","SDMA","GMC","VCN","PSP","RLC","MEC","KFD","IH","DCN","MMHUB","GCHUB","JPEG","SMU"}
    assert required == set(AMD_IP_BLOCKS)

def test_nvidia_ip_blocks():
    from soctriage.providers.nvidia.ip_definitions import NVIDIA_IP_BLOCKS
    assert len(NVIDIA_IP_BLOCKS) == 10


# ── AC-P0-07: ip_definitions data dicts correct types (not None) ─────────────
@pytest.mark.parametrize("module_path", [
    "soctriage.providers.intel.ip_definitions",
    "soctriage.providers.qualcomm.ip_definitions",
    "soctriage.providers.amd.ip_definitions",
    "soctriage.providers.nvidia.ip_definitions",
])
def test_ip_definitions_types(module_path):
    import importlib
    ipd = importlib.import_module(module_path)
    assert isinstance(ipd.IP_PATTERNS,   dict)
    assert isinstance(ipd.CASCADE_GRAPH, dict)
    assert isinstance(ipd.PLAYBOOK,      dict)
    assert isinstance(ipd.REGISTER_MAPS, dict)
    assert isinstance(ipd.HANG_RULES,    list)


# ── AC-P0-08: All 37 fixtures exist ──────────────────────────────────────────
@pytest.mark.parametrize("fixture_path", ALL_FIXTURES)
def test_fixture_exists(fixture_path):
    assert (FIXTURES / fixture_path).exists(), f"Missing: {fixture_path}"


# ── AC-P0-09: Non-empty fixtures openable ────────────────────────────────────
@pytest.mark.parametrize("fixture_path",
    [f for f in ALL_FIXTURES if f != "generic/empty.log"])
def test_fixture_openable(fixture_path):
    with open(FIXTURES / fixture_path, "rb") as fh:
        assert len(fh.read(1)) >= 1


# ── AC-P0-10: Empty fixture is 0 bytes ───────────────────────────────────────
def test_empty_fixture_zero_bytes():
    assert (FIXTURES / "generic/empty.log").stat().st_size == 0


# ── AC-P0-11: Binary fixture has non-UTF8 bytes ──────────────────────────────
def test_binary_fixture_has_invalid_utf8():
    raw = (FIXTURES / "generic/binary_contaminated.log").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


# ── AC-P0-12: CLI --list-providers exits 0 and mentions all 4 SoCs ───────────
def test_cli_list_providers():
    result = subprocess.run(
        [sys.executable, "-m", "soctriage.cli", "--list-providers"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    for name in ["Intel", "Qualcomm", "AMD", "NVIDIA", "Generic"]:
        assert name in result.stdout, f"{name} missing from --list-providers output"


# ── AC-P0-13: Exit code constants ────────────────────────────────────────────
def test_exit_code_constants():
    from soctriage.cli import EXIT_SUCCESS, EXIT_NO_ANOMALY, EXIT_PARSE_ERR, EXIT_INPUT_ERR
    assert EXIT_SUCCESS == 0
    assert EXIT_NO_ANOMALY == 1
    assert EXIT_PARSE_ERR  == 2
    assert EXIT_INPUT_ERR  == 3


# ── AC-P0-14: OUTPUT_SCHEMA structure ────────────────────────────────────────
def test_output_schema_structure():
    from soctriage.core.reporter import OUTPUT_SCHEMA
    required = {"kernel_version","architecture","asic_generation",
                "soc_provider","total_events","events"}
    assert required.issubset(set(OUTPUT_SCHEMA.keys()))
    assert "ip_root_cause"    in OUTPUT_SCHEMA["events"][0]
    assert "ip_cascade_chain" in OUTPUT_SCHEMA["events"][0]
    assert "llm_rca"          in OUTPUT_SCHEMA["events"][0]


# ── AC-P0-15: All manifest.yaml files load cleanly ───────────────────────────
@pytest.mark.parametrize("provider_dir", ["intel", "qualcomm", "amd", "nvidia"])
def test_manifest_yaml_loads(provider_dir):
    path = Path(f"soctriage/providers/{provider_dir}/manifest.yaml")
    with open(path) as fh:
        data = yaml.safe_load(fh)
    assert "name"             in data
    assert "detection_keywords" in data
    assert len(data["detection_keywords"]) >= 5


# ── AC-P0-16: HangRule dataclass ─────────────────────────────────────────────
def test_hang_rule_dataclass():
    from soctriage.core.soc_provider import HangRule
    rule = HangRule(mode="HANG", signals=[r"ring timeout"], confidence=0.95)
    assert rule.mode == "HANG"
    assert isinstance(rule.signals, list)
    assert rule.confidence == 0.95


# ── AC-P0-17: ProviderRegistry has correct method signatures ─────────────────
def test_provider_registry_signatures():
    from soctriage.core.provider_registry import ProviderRegistry
    registry = ProviderRegistry()
    for method in ["register", "auto_discover", "detect_provider", "list_providers"]:
        assert hasattr(registry, method), f"Missing method: {method}"


# ── AC-P0-18: PROVIDER_PRIORITY order correct ────────────────────────────────
def test_provider_priority_order():
    from soctriage.core.provider_registry import PROVIDER_PRIORITY
    assert PROVIDER_PRIORITY[0] == "intel"
    assert PROVIDER_PRIORITY[1] == "qualcomm"
    assert PROVIDER_PRIORITY[2] == "amd"
    assert PROVIDER_PRIORITY[3] == "nvidia"
    assert PROVIDER_PRIORITY[-1] == "generic"


# ════════════════════════════════════════════════════════════════════════════
# XFAIL stubs — known future work, visible in pytest output
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(reason="Phase 1: EC-01 normal dmesg → no anomalies")
def test_ec01_normal_dmesg_no_anomalies():
    raise NotImplementedError

@pytest.mark.xfail(reason="Phase 1: EC-06 >100MB log streams without OOM")
def test_ec06_large_log_streaming():
    raise NotImplementedError

@pytest.mark.xfail(reason="Phase 1: EC-10 empty file → EC-10 structured error + exit 3")
def test_ec10_empty_file_structured_error():
    raise NotImplementedError

@pytest.mark.xfail(reason="Phase 1: EC-12 .gz/.bz2/.xz auto-decompressed")
def test_ec12_compressed_log_decompression():
    raise NotImplementedError

@pytest.mark.xfail(reason="Phase 3: EC-09 KASAN classified as root over amdgpu")
def test_ec09_kasan_root_over_amdgpu():
    raise NotImplementedError

@pytest.mark.xfail(reason="Phase 3: EC-18 multi-GPU → separate cascade per PCI bus ID")
def test_ec18_multi_gpu_per_pci_bus():
    raise NotImplementedError


# ════════════════════════════════════════════════════════════════════════════
# v1.1.0 — YAML Plugin Architecture Scaffold
# ════════════════════════════════════════════════════════════════════════════

RULES = Path(__file__).parent.parent / "soctriage" / "core" / "token_rules"


# ── YAML plugin scaffold (3 tests — PASSED) ──────────────────────────────────

def test_token_rules_directory_exists():
    """token_rules/ directory must exist at scaffold time."""
    assert RULES.is_dir(), f"Missing directory: {RULES}"

def test_core_kernel_yaml_stub_exists():
    """core_kernel.yaml stub must exist — Phase 2b populates it."""
    stub = RULES / "core_kernel.yaml"
    assert stub.exists(), "Missing core_kernel.yaml stub"
    data = yaml.safe_load(stub.read_text())
    assert data.get("version") == 1
    assert data.get("category") == "core_kernel"
    assert "rules" in data

def test_custom_yaml_stub_exists():
    """custom.yaml must exist and be valid YAML."""
    stub = RULES / "custom.yaml"
    assert stub.exists(), "Missing custom.yaml stub"
    data = yaml.safe_load(stub.read_text())
    assert data.get("category") == "custom"
    assert isinstance(data.get("rules"), list)


# ── token_rule.py stubs (2 tests — PASSED) ───────────────────────────────────

def test_token_rule_classes_importable():
    """TokenRule, CompiledRule, TokenRuleRegistry must be importable."""
    from soctriage.core.token_rule import TokenRule, CompiledRule, TokenRuleRegistry
    assert TokenRule is not None
    assert CompiledRule is not None
    assert TokenRuleRegistry is not None

def test_token_rule_registry_instantiates():
    """TokenRuleRegistry() must instantiate without error."""
    from soctriage.core.token_rule import TokenRuleRegistry
    reg = TokenRuleRegistry()
    assert reg is not None


# ── tokenize() signature check (1 test — PASSED) ─────────────────────────────

def test_tokenize_has_rule_registry_param():
    """tokenize() must accept rule_registry=None (v1.1.0 addition)."""
    import inspect
    from soctriage.core.tokenizer import tokenize
    sig = inspect.signature(tokenize)
    assert "rule_registry" in sig.parameters
    assert sig.parameters["rule_registry"].default is None


# ── XFAIL: Phase 2b pending (1 test — XFAIL) ─────────────────────────────────

@pytest.mark.xfail(reason="Phase 2b — TokenRuleRegistry.load_defaults() not implemented")
def test_token_rule_registry_loads_yaml():
    """Phase 2b will implement load_defaults() to load all YAML files."""
    from soctriage.core.token_rule import TokenRuleRegistry
    reg = TokenRuleRegistry()
    reg.load_defaults()
    assert reg.rule_count() > 0
