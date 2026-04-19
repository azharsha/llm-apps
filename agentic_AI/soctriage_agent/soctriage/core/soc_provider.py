from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass


@dataclass
class HangRule:
    mode:       str          # "HANG" | "STALL" | "ERROR" | "SOFT-HANG" | "HARD-HANG"
    signals:    list[str]    # regex patterns — injected by provider
    confidence: float        # 0.0 – 1.0


class SoCProvider(ABC):

    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name, e.g. 'Intel Xe/Gen Graphics'."""

    @abstractmethod
    def detect(self, raw_log: str) -> float:
        """Return confidence [0.0–1.0] that this log belongs to this SoC."""

    @abstractmethod
    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map token stream to IP block hits with confidence scores.
        Returns: [{"ip": "GUC", "confidence": 0.92}, ...]
        """

    @abstractmethod
    def resolve_cascade(self, ip_hits: list[dict[str, Any]]) -> list[str]:
        """Return ordered cascade chain from primary fault IP to downstream IPs."""

    @abstractmethod
    def get_playbook(self, ip_block: str) -> dict[str, Any]:
        """Return structured fix playbook for a given IP block."""

    @abstractmethod
    def decode_registers(self, raw_registers: dict[str, int]) -> dict[str, Any]:
        """Decode raw register hex values to named fields and fault states."""

    @abstractmethod
    def get_register_maps(self) -> dict[str, dict[int, str]]:
        """Return register name to bit-field definitions.
        Core ScanDumpParser uses this. Provider owns all register definitions.
        """

    @abstractmethod
    def get_hang_rules(self) -> list[HangRule]:
        """Return ordered HangRule list for StallClassifier.
        Provider owns all hang detection logic. Core only scores.
        """
