from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule
from soctriage.providers.amd.ip_definitions import REGISTER_MAPS

# Detection keywords sourced from manifest.yaml detection_keywords
_DETECT_KEYWORDS: list[str] = [
    "amdgpu", "drm/amd", "GRBM_STATUS", "amd_iommu",
    "kfd", "amdgpu_psp", "SDMA_STATUS", "CP_STALLED",
]


class AMDProvider(SoCProvider):

    def name(self) -> str:
        return "AMD RDNA/CDNA"

    def detect(self, raw_log: str) -> float:
        """Return confidence that this log belongs to an AMD GPU/SoC."""
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
