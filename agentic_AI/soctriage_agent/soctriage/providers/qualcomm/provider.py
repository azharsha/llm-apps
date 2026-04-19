from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule
from soctriage.providers.qualcomm.ip_definitions import REGISTER_MAPS

# Detection keywords sourced from manifest.yaml detection_keywords
_DETECT_KEYWORDS: list[str] = [
    "msm", "qcom", "adreno", "kgsl", "qcom_smmu",
    "dwc3-msm", "qmp-phy", "llcc", "venus", "camss",
]


class QualcommProvider(SoCProvider):

    def name(self) -> str:
        return "Qualcomm MSM/Snapdragon"

    def detect(self, raw_log: str) -> float:
        """Return confidence that this log belongs to a Qualcomm SoC."""
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
