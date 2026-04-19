from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule
from soctriage.providers.intel.ip_definitions import REGISTER_MAPS

# Detection keywords sourced from manifest.yaml detection_keywords
_DETECT_KEYWORDS: list[str] = [
    "i915", "xe driver", "drm/i915", "GuC", "HuC",
    "intel_iommu", "thunderbolt", "usb4", "GEN12",
    "Xe HP", "DG2", "Flex Series", "Meteor Lake",
]


class IntelProvider(SoCProvider):

    def name(self) -> str:
        return "Intel Xe/Gen Graphics"

    def detect(self, raw_log: str) -> float:
        """Return confidence that this log belongs to an Intel GPU/SoC."""
        hits = sum(1 for kw in _DETECT_KEYWORDS if kw in raw_log)
        return min(1.0, hits * 0.25)

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

    def resolve_cascade(self, ip_hits: list[dict[str, Any]]) -> list[str]:
        return []

    def get_playbook(self, ip_block: str) -> dict[str, Any]:
        return {}

    def decode_registers(self, raw_registers: dict[str, int]) -> dict[str, Any]:
        return {}

    def get_register_maps(self) -> dict[str, dict[int, str]]:
        return REGISTER_MAPS

    def get_hang_rules(self) -> list[HangRule]:
        return []
