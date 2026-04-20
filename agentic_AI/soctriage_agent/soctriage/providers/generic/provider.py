from __future__ import annotations

from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule


_IP_MAP: dict[str, tuple[str, float, str]] = {
    "gpu_event":      ("GPU",      0.40, "gpu"),
    "firmware_event": ("FIRMWARE", 0.40, "firmware"),
    "memory_event":   ("MEMORY",   0.40, "memory"),
    "pcie_error":     ("PCIE",     0.40, "interconnect"),
    "smmu_fault":     ("IOMMU",    0.40, "interconnect"),
    "storage_fail":   ("STORAGE",  0.40, "storage"),
    "power_fault":    ("POWER",    0.40, "power"),
}


class GenericProvider(SoCProvider):
    """Fallback provider — matches any log with low confidence (0.1)."""

    def name(self) -> str:
        return "Generic"

    def detect(self, raw_log: str) -> float:
        """Always returns 0.1 — acts as guaranteed fallback."""
        return 0.1

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map token_type → IP block. First match wins; dedup by IP name."""
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for token in token_stream:
            token_type = token.get("type", "")
            if token_type not in _IP_MAP:
                continue
            ip_name, confidence, subsystem = _IP_MAP[token_type]
            if ip_name in seen:
                continue
            seen.add(ip_name)
            results.append(
                {
                    "ip": ip_name,
                    "confidence": confidence,
                    "subsystem": subsystem,
                    "notes": "generic fallback",
                }
            )
        return results

    def get_known_issues(
        self,
        chip_gen: str,
        event_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generic provider has no known-issue database."""
        return []

    def resolve_cascade(self, ip_hits: list[dict[str, Any]]) -> list[str]:
        return []

    def get_playbook(self, ip_block: str) -> dict[str, Any]:
        return {}

    def decode_registers(self, raw_registers: dict[str, int]) -> dict[str, Any]:
        return {}

    def get_register_maps(self) -> dict[str, dict[int, str]]:
        return {}

    def get_hang_rules(self) -> list[HangRule]:
        return []
