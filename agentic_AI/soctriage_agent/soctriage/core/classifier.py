"""
classifier.py — Phase 3 v3.0.0

Classifies LogEvent objects into subsystem buckets, assigns IP block via
SoCProvider adapter, and computes per-event confidence scores.

Two public symbols: EventClassifier and classify_all().
Never modifies soc_provider.py — uses _call_classify_ip() adapter.
"""

from __future__ import annotations

import logging
from typing import Iterator

from soctriage.core.assembler import LogEvent
from soctriage.core.soc_provider import SoCProvider
from soctriage.core.tokenizer import LogToken

__all__ = ["EventClassifier", "classify_all"]

logger = logging.getLogger(__name__)

# ── Confidence formula constants ──────────────────────────────────────────────

_BASE_CONF_KNOWN:    float = 0.5   # known subsystem base
_BASE_CONF_UNKNOWN:  float = 0.3   # unknown subsystem base
_BONUS_CALL_TRACE:   float = 0.2   # has call trace in tokens
_BONUS_REGISTERS:    float = 0.1   # has register dump in tokens
_BONUS_CHIP_KNOWN:   float = 0.1   # chip_gen detected (not "unknown")
_BONUS_SEVERITY_CRIT: float = 0.1  # event severity is critical

# ── Subsystem routing table (token_type → subsystem) ─────────────────────────

_SUBSYSTEM_MAP: dict[str, str] = {
    # CPU
    "panic":              "cpu",
    "oops_header":        "cpu",
    "lockup_soft":        "cpu",
    "lockup_hard":        "cpu",
    "cpu_hotplug":        "cpu",
    "preempt_fault":      "cpu",
    "sched_stall":        "cpu",
    # GPU
    "gpu_event":          "gpu",
    "reset_event":        "gpu",
    "timeout_event":      "gpu",
    "sync_fence_event":   "gpu",
    "gem_event":          "gpu",
    "gfx_cp_event":       "gpu",
    # Display
    "display_event":      "display",
    "encoder_event":      "display",
    "drm_bridge_event":   "display",
    "dp_link_fail":       "display",
    "mipi_dsi_event":     "display",
    # Memory
    "memory_event":       "memory",
    "kasan_detail":       "memory",
    "memory_poison":      "memory",
    "oom_event":          "memory",
    "dma_fault":          "memory",
    "numa_fault":         "memory",
    # Interconnect
    "pcie_error":         "interconnect",
    "axi_fault":          "interconnect",
    "smmu_fault":         "interconnect",
    "crc_error":          "interconnect",
    # Storage
    "ufs_event":          "storage",
    "nvme_event":         "storage",
    "emmc_event":         "storage",
    "io_error":           "storage",
    # Power
    "thermal_event":      "power",
    "voltage_event":      "power",
    "clk_event":          "power",
    "power_event":        "power",
    # Network
    "network_event":      "network",
    "roce_event":         "network",
    "infiniband_event":   "network",
    # Firmware
    "firmware_event":     "firmware",
    "bootloader_event":   "firmware",
    "tee_event":          "firmware",
    "secure_boot_event":  "firmware",
    "module_event":       "firmware",
    # SoC platform
    "gic_event":          "soc_platform",
    "wdt_event":          "soc_platform",
    "acpi_event":         "soc_platform",
    "spmi_event":         "soc_platform",
    "reset_ctrl_event":   "soc_platform",
    # Remoteproc
    "remoteproc_event":   "remoteproc",
    "remoteproc_crash":   "remoteproc",
    "rpmsg_event":        "remoteproc",
    "qcom_adsp_crash":    "remoteproc",
    "qcom_cdsp_crash":    "remoteproc",
    "qcom_slpi_crash":    "remoteproc",
    # Security
    "audit_event":        "security",
    "sanitizer_event":    "security",
    "speculation_fault":  "security",
    "tpm_event":          "security",
    # Virt
    "kvm_event":          "virt",
    "vfio_event":         "virt",
    "cgroup_event":       "virt",
    "xen_grant_fail":     "virt",
    "hyperv_vmbus_event": "virt",
    # Debug
    "ramoops_event":      "debug",
    "ras_event":          "debug",
    "kunit_event":        "debug",
    "ftrace_event":       "debug",
    "kgdb_event":         "debug",
}


# ── _call_classify_ip adapter ─────────────────────────────────────────────────


def _call_classify_ip(provider: SoCProvider, tok: LogToken) -> str:
    """Adapt the locked classify_ip(list[dict])->list[dict] to per-token usage."""
    try:
        result = provider.classify_ip([{"type": tok.token_type, "raw": tok.raw}])
        if result and isinstance(result, list) and result[0].get("ip"):
            return str(result[0]["ip"])
        return "unknown"
    except NotImplementedError:
        return "unknown"
    except (KeyError, IndexError, TypeError) as exc:
        logger.debug(
            "classify_ip failed for token_type=%r provider=%s: %r",
            tok.token_type, provider.name(), exc,
        )
        return "unknown"


# ── Confidence formula ────────────────────────────────────────────────────────


def _compute_confidence(event: LogEvent) -> float:
    """
    Confidence heuristic:
      known subsystem     → _BASE_CONF_KNOWN base, else _BASE_CONF_UNKNOWN
      has_call_trace      → +_BONUS_CALL_TRACE
      has_registers       → +_BONUS_REGISTERS
      chip_gen known      → +_BONUS_CHIP_KNOWN
      severity critical   → +_BONUS_SEVERITY_CRIT
    Capped at 1.0.
    """
    score = _BASE_CONF_KNOWN if event.subsystem != "unknown" else _BASE_CONF_UNKNOWN
    if event.has_call_trace:         score += _BONUS_CALL_TRACE
    if event.has_registers:          score += _BONUS_REGISTERS
    if event.chip_gen != "unknown":  score += _BONUS_CHIP_KNOWN
    if event.severity == "critical": score += _BONUS_SEVERITY_CRIT
    return min(score, 1.0)


# ── EventClassifier ───────────────────────────────────────────────────────────


class EventClassifier:
    """
    Classifies a LogEvent in-place:
    - subsystem: first token type found in _SUBSYSTEM_MAP wins; fallback "unknown"
    - ip_block:  delegated to _call_classify_ip() adapter; "unknown" if unavailable
    - confidence: computed by _compute_confidence()
    - provider_name: provider.name() or "generic"
    """

    def __init__(self, provider: SoCProvider | None = None) -> None:
        self._provider = provider

    def classify(self, event: LogEvent) -> LogEvent:
        """Classify event in-place and return it."""
        # ── Subsystem — first matching token type wins ─────────────────────
        subsystem = "unknown"
        for tok in event.tokens:
            if tok.token_type in _SUBSYSTEM_MAP:
                subsystem = _SUBSYSTEM_MAP[tok.token_type]
                break
        event.subsystem = subsystem

        # ── IP block — delegate to provider via adapter ────────────────────
        ip_block = "unknown"
        if self._provider is not None:
            for tok in event.tokens:
                result = _call_classify_ip(self._provider, tok)
                if result != "unknown":
                    ip_block = result
                    break
        event.ip_block = ip_block

        # ── Provider name ──────────────────────────────────────────────────
        event.provider_name = self._provider.name() if self._provider is not None else "generic"

        # ── Confidence ─────────────────────────────────────────────────────
        event.confidence = _compute_confidence(event)

        return event


# ── Pipeline helper ───────────────────────────────────────────────────────────


def classify_all(
    events: Iterator[LogEvent],
    provider: SoCProvider | None = None,
) -> Iterator[LogEvent]:
    """
    Classify every LogEvent in the stream.
    Thin wrapper over EventClassifier — one-liner pipeline usage.

    Usage:
        for e in classify_all(assemble(tokenize(open_log("crash.log")[0]))):
            print(e.event_type, e.subsystem, e.confidence)
    """
    clf = EventClassifier(provider=provider)
    for event in events:
        yield clf.classify(event)
