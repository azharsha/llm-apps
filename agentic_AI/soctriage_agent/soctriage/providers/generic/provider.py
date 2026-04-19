from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule


class GenericProvider(SoCProvider):
    """Fallback provider — matches any log with low confidence (0.1)."""

    def name(self) -> str:
        return "Generic"

    def detect(self, raw_log: str) -> float:
        """Always returns 0.1 — acts as guaranteed fallback."""
        return 0.1

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
