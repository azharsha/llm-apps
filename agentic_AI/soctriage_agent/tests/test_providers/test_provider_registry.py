"""12 tests for ProviderRegistry — Phase 5 T7."""
from __future__ import annotations

from pathlib import Path

import pytest

from soctriage.core.provider_registry import ProviderRegistry, PROVIDER_PRIORITY
from soctriage.core.soc_provider import SoCProvider
from soctriage.providers.generic.provider import GenericProvider
from soctriage.providers.intel.provider import IntelProvider
from soctriage.providers.qualcomm.provider import QualcommProvider
from soctriage.providers.amd.provider import AMDProvider
from soctriage.providers.nvidia.provider import NVIDIAProvider

PROVIDERS_DIR = Path("soctriage/providers")

# ── Logs that strongly identify each vendor ────────────────────────────────────

_INTEL_LOG = (
    "i915 drm/i915: GuC firmware load failed\n"
    "intel_iommu: DMAR fault addr 0x1000\n"
    "[ 5.123456] i915 0000:00:02.0: [drm] GuC/HuC firmware failed"
)

_QCOM_LOG = (
    "qcom msm-adsp: ADSP crash detected\n"
    "qcom-smmu: arm-smmu context fault\n"
    "kgsl: adreno GPU hang detected"
)

_AMD_LOG = (
    "amdgpu: GPU HANG detected on ring gfx\n"
    "amdgpu: GRBM_STATUS: 0xC0000000 GUI_ACTIVE\n"
    "drm/amd/amdgpu: ras: uncorrectable error detected\n"
    "amd_iommu: IOMMU fault on device 0000:03:00.0"
)

_NVIDIA_LOG = (
    "nvidia NVRM: GPU-0:00:1e.0 XID 79 timeout\n"
    "nvidia NVRM: GSP firmware timeout\n"
    "nvidia-smi: GPU-0 Xid=79 Channel 0"
)

_GENERIC_LOG = "kernel: BUG: unable to handle kernel NULL pointer dereference"


# ── 1. ProviderRegistry instantiates cleanly ─────────────────────────────────

def test_registry_instantiates():
    reg = ProviderRegistry()
    assert reg is not None


# ── 2. Empty registry returns empty list ─────────────────────────────────────

def test_empty_registry_list_providers_is_empty():
    reg = ProviderRegistry()
    assert reg.list_providers() == []


# ── 3. register() adds a provider ────────────────────────────────────────────

def test_register_adds_provider():
    reg = ProviderRegistry()
    reg.register(GenericProvider())
    assert len(reg.list_providers()) == 1


# ── 4. list_providers() returns names ────────────────────────────────────────

def test_list_providers_returns_names():
    reg = ProviderRegistry()
    reg.register(IntelProvider())
    reg.register(GenericProvider())
    names = reg.list_providers()
    assert "Intel Xe/Gen Graphics" in names
    assert len(names) == 2


# ── 5. auto_discover() finds all 5 providers ─────────────────────────────────

def test_auto_discover_finds_five_providers():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    assert len(reg.list_providers()) == 5


# ── 6. auto_discover() order follows PROVIDER_PRIORITY ───────────────────────

def test_auto_discover_order_matches_priority():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    names = reg.list_providers()
    # Generic must be last
    assert "Generic" in names[-1]
    # Intel must appear before Qualcomm
    intel_idx = next(i for i, n in enumerate(names) if "Intel" in n)
    qcom_idx = next(i for i, n in enumerate(names) if "Qualcomm" in n)
    amd_idx = next(i for i, n in enumerate(names) if "AMD" in n)
    nvidia_idx = next(i for i, n in enumerate(names) if "NVIDIA" in n)
    assert intel_idx < qcom_idx < amd_idx < nvidia_idx


# ── 7. detect_provider() routes Intel log → IntelProvider ────────────────────

def test_detect_provider_intel_log():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    provider = reg.detect_provider(_INTEL_LOG)
    assert isinstance(provider, IntelProvider)


# ── 8. detect_provider() routes Qualcomm log → QualcommProvider ──────────────

def test_detect_provider_qualcomm_log():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    provider = reg.detect_provider(_QCOM_LOG)
    assert isinstance(provider, QualcommProvider)


# ── 9. detect_provider() routes AMD log → AMDProvider ────────────────────────

def test_detect_provider_amd_log():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    provider = reg.detect_provider(_AMD_LOG)
    assert isinstance(provider, AMDProvider)


# ── 10. detect_provider() routes NVIDIA log → NVIDIAProvider ─────────────────

def test_detect_provider_nvidia_log():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    provider = reg.detect_provider(_NVIDIA_LOG)
    assert isinstance(provider, NVIDIAProvider)


# ── 11. detect_provider() falls back to Generic for unknown log ───────────────

def test_detect_provider_generic_fallback():
    reg = ProviderRegistry()
    reg.auto_discover(PROVIDERS_DIR)
    provider = reg.detect_provider(_GENERIC_LOG)
    assert isinstance(provider, GenericProvider)


# ── 12. detect_provider() on empty registry returns GenericProvider ───────────

def test_detect_provider_empty_registry_returns_generic():
    reg = ProviderRegistry()
    provider = reg.detect_provider("anything here")
    assert isinstance(provider, GenericProvider)
