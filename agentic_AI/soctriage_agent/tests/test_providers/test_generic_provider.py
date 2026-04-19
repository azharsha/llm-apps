from __future__ import annotations

import string
import random

import pytest

from soctriage.providers.generic.provider import GenericProvider
from soctriage.core.soc_provider import SoCProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider() -> GenericProvider:
    return GenericProvider()


def _tok(token_type: str) -> dict:
    return {"token_type": token_type, "raw": "dummy"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_name_returns_generic():
    assert _provider().name() == "Generic"


def test_detect_returns_float_in_range():
    result = _provider().detect("any string")
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_detect_returns_point_one_always():
    assert _provider().detect("i915 GuC firmware") == 0.1


def test_detect_returns_point_one_empty():
    assert _provider().detect("") == 0.1


def test_classify_ip_empty_returns_empty_list():
    assert _provider().classify_ip([]) == []


def test_classify_ip_unknown_type_returns_empty():
    result = _provider().classify_ip([_tok("unknown_token_xyz")])
    assert result == []


def test_classify_ip_gpu_event_returns_gpu():
    result = _provider().classify_ip([_tok("gpu_event")])
    assert len(result) == 1
    hit = result[0]
    assert hit["ip"] == "GPU"
    assert hit["confidence"] == 0.40
    assert hit["subsystem"] == "gpu"


def test_classify_ip_firmware_event_returns_firmware():
    result = _provider().classify_ip([_tok("firmware_event")])
    assert len(result) == 1
    hit = result[0]
    assert hit["ip"] == "FIRMWARE"
    assert hit["confidence"] == 0.40
    assert hit["subsystem"] == "firmware"


def test_classify_ip_pcie_error_returns_pcie():
    result = _provider().classify_ip([_tok("pcie_error")])
    assert len(result) == 1
    hit = result[0]
    assert hit["ip"] == "PCIE"
    assert hit["subsystem"] == "interconnect"


def test_classify_ip_smmu_fault_returns_iommu():
    result = _provider().classify_ip([_tok("smmu_fault")])
    assert len(result) == 1
    hit = result[0]
    assert hit["ip"] == "IOMMU"
    assert hit["subsystem"] == "interconnect"


def test_classify_ip_result_has_required_keys():
    result = _provider().classify_ip([_tok("gpu_event")])
    assert len(result) == 1
    hit = result[0]
    for key in ("ip", "confidence", "subsystem", "notes"):
        assert key in hit, f"Missing key: {key}"


def test_classify_ip_never_raises_for_any_input():
    random_types = [
        "".join(random.choices(string.ascii_lowercase + "_", k=random.randint(3, 20)))
        for _ in range(20)
    ]
    provider = _provider()
    for tt in random_types:
        try:
            provider.classify_ip([_tok(tt)])
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"classify_ip raised {type(exc).__name__} for token_type={tt!r}: {exc}")


def test_resolve_cascade_empty_returns_empty():
    assert _provider().resolve_cascade([]) == []


def test_get_playbook_unknown_returns_empty_dict():
    assert _provider().get_playbook("anything") == {}


def test_is_soc_provider_instance():
    assert isinstance(GenericProvider(), SoCProvider)
