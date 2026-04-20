from __future__ import annotations
import re
from typing import Any
from soctriage.core.soc_provider import SoCProvider, HangRule
from soctriage.providers.qualcomm.ip_definitions import (
    CLASSIFY_RULES, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES, KNOWN_ISSUES,
)

_DETECT_KEYWORDS: list[str] = [
    "msm", "qcom", "adreno", "kgsl", "qcom_smmu",
    "dwc3-msm", "qmp-phy", "llcc", "venus", "camss",
]
_DETECT_PATTERNS = [
    re.compile(r"ADSP crash|adsp.*fault", re.IGNORECASE),
    re.compile(r"qcom.*smmu|arm-smmu.*qcom", re.IGNORECASE),
]


class QualcommProvider(SoCProvider):

    def name(self) -> str:
        return "Qualcomm MSM/Snapdragon"

    def detect(self, raw_log: str) -> float:
        hits = sum(1 for kw in _DETECT_KEYWORDS if kw in raw_log)
        bonus = sum(0.15 for p in _DETECT_PATTERNS if p.search(raw_log))
        return min(1.0, hits * 0.25 + bonus)

    def classify_ip(self, token_stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_ips: set[str] = set()
        for tok in token_stream:
            tok_type = tok.get("type", "")
            raw = tok.get("raw", "")
            for rule_type, pattern, ip, conf, subsys in CLASSIFY_RULES:
                if rule_type == tok_type and (not pattern or pattern in raw):
                    if ip not in seen_ips:
                        results.append({
                            "ip": ip,
                            "confidence": conf,
                            "subsystem": subsys,
                            "notes": f"matched {tok_type}" + (f" via '{pattern}'" if pattern else ""),
                        })
                        seen_ips.add(ip)
                    break
        return results

    def resolve_cascade(self, ip_hits: list[dict[str, Any]]) -> list[str]:
        if not ip_hits:
            return []
        primary = max(ip_hits, key=lambda x: x.get("confidence", 0.0))["ip"]
        chain = [primary]
        present = {h["ip"] for h in ip_hits}
        for ip in CASCADE_GRAPH.get(primary, []):
            if ip in present and ip not in chain:
                chain.append(ip)
        return chain

    def get_playbook(self, ip_block: str) -> dict[str, Any]:
        return PLAYBOOK.get(ip_block, {})

    def decode_registers(self, raw_registers: dict[str, int]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for reg, value in raw_registers.items():
            fields: dict[str, bool] = {}
            for mask, name in REGISTER_MAPS.get(reg, {}).items():
                fields[name] = bool(value & mask)
            result[reg] = {"raw": value, "fields": fields}
        return result

    def get_register_maps(self) -> dict[str, dict[int, str]]:
        return {k: dict(v) for k, v in REGISTER_MAPS.items()}

    def get_hang_rules(self) -> list[HangRule]:
        return list(HANG_RULES)

    def get_known_issues(self, chip_gen: str, event_types: list[str] | None = None) -> list[dict]:
        event_types = event_types or []
        result = []
        for issue in KNOWN_ISSUES:
            if chip_gen not in issue["chip_gens"]:
                continue
            if event_types and not (set(issue["symptoms"]) & set(event_types)):
                continue
            result.append(issue)
        return result
