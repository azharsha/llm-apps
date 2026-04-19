"""
assembler.py — Phase 3 v3.0.0

Assembles a raw LogToken stream from Phase 2 into structured LogEvent objects.
Two public symbols: LogEvent (dataclass) and assemble() (generator).

Frozen after Phase 3 — do not modify token_rule.py, tokenizer.py,
soc_provider.py, cli.py, or reporter.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator, Any

from soctriage.core.tokenizer import LogToken

__all__ = ["LogEvent", "assemble"]


# ── Public dataclass ──────────────────────────────────────────────────────────


@dataclass
class LogEvent:
    event_id:       int              # 1-based, unique within the log
    event_type:     str              # see taxonomy — never None
    severity:       str              # "critical" | "error" | "warning" | "info"
    subsystem:      str              # 15-bucket taxonomy — "unknown" fallback
    ip_block:       str              # from _call_classify_ip() or "unknown"
    tokens:         list[LogToken]   # ordered, no duplicates if skip_duplicates=True
    start_line:     int              # line_no of first token
    end_line:       int              # line_no of last token
    arch:           str              # inherited from tokens[0]
    chip_gen:       str              # inherited from tokens[0]
    kernel_ver:     str | None       # inherited from tokens[0]
    confidence:     float            # 0.0–1.0 (set by classifier)
    raw_text:       str              # "\n".join(t.raw for t in tokens)
    has_call_trace: bool             # any token.token_type == "call_trace_frame"
    has_registers:  bool             # any t.token_type in {"register_dump","register_arm64"}
    provider_name:  str              # provider.name() or "generic"


# ── State machine ─────────────────────────────────────────────────────────────


class _State(Enum):
    IDLE     = auto()
    IN_EVENT = auto()


# ── Token-set constants ───────────────────────────────────────────────────────

BOUNDARY_TOKEN_TYPES: frozenset[str] = frozenset({
    # Core kernel
    "panic", "oops_header", "lockup_soft", "lockup_hard",
    "deadlock", "rcu_stall", "hung_task", "stack_overflow", "mce_error",
    # GPU
    "gpu_event", "reset_event",
    # Memory
    "memory_event", "oom_event", "memory_poison",
    # Firmware
    "firmware_event", "bootloader_event", "tee_event",
    # Interconnect
    "pcie_error", "axi_fault", "smmu_fault", "dma_fault",
    # Power
    "thermal_event", "voltage_event", "clk_event",
    # SoC platform
    "gic_event", "wdt_event", "spmi_bus_error",
    "reset_assert_fail", "reset_deassert_fail",
    "phy_init_fail", "phy_calibration_fail",
    # Storage
    "ufs_event", "nvme_event", "emmc_event", "io_error",
    # Remoteproc / Qualcomm PD
    "remoteproc_crash", "remoteproc_fw_fail",
    "qcom_adsp_crash", "qcom_cdsp_crash", "qcom_slpi_crash", "qcom_pil_event",
    # AMD PSP
    "amd_psp_fw_fail", "amd_sev_event",
    # Security
    "sanitizer_event", "secure_boot_event",
    # Hypervisor
    "hyperv_vmbus_event", "xen_grant_fail",
    # NOTE: "warning" is intentionally NOT here — handled by line-distance logic
})

CONTINUATION_TOKEN_TYPES: frozenset[str] = frozenset({
    "call_trace_header", "call_trace_frame",
    "register_dump", "register_arm64",
    "separator",                      # CONTINUATION takes precedence over INFO
    "timeout_event", "sync_fence_event",
    "gem_event", "gfx_cp_event",
    "kasan_detail", "kasan_shadow_event",
    "oops_arm64_specific",
    "irq_error", "nmi_event",
})

INFO_TOKEN_TYPES: frozenset[str] = frozenset({
    "info", "unknown",
    "tracepoint", "ftrace_event", "kunit_event",
    # "separator" intentionally excluded here — it's in CONTINUATION
})

# ── Event type and severity maps ──────────────────────────────────────────────

_EVENT_TYPE_MAP: dict[str, str] = {
    "panic":                "kernel_panic",
    "oops_header":          "kernel_oops",
    "gpu_event":            "gpu_hang",
    "reset_event":          "gpu_reset",
    "timeout_event":        "gpu_timeout",
    "firmware_event":       "firmware_fail",
    "memory_event":         "memory_fault",
    "kasan_detail":         "memory_fault",
    "memory_poison":        "memory_fault",
    "oom_event":            "oom_kill",
    "lockup_soft":          "lockup",
    "lockup_hard":          "lockup",
    "deadlock":             "deadlock",
    "rcu_stall":            "rcu_stall",
    "hung_task":            "hung_task",
    "pcie_error":           "pcie_fault",
    "smmu_fault":           "smmu_fault",
    "dma_fault":            "dma_fault",
    "thermal_event":        "power_fault",
    "voltage_event":        "power_fault",
    "clk_event":            "power_fault",
    "qcom_adsp_crash":      "soc_crash",
    "qcom_cdsp_crash":      "soc_crash",
    "qcom_slpi_crash":      "soc_crash",
    "remoteproc_crash":     "remoteproc_fail",
    "remoteproc_fw_fail":   "remoteproc_fail",
    "ufs_event":            "storage_fail",
    "nvme_event":           "storage_fail",
    "emmc_event":           "storage_fail",
    "phy_init_fail":        "phy_fail",
    "phy_calibration_fail": "phy_fail",
    "warning":              "warning_event",
    "audit_event":          "security_event",
    "sanitizer_event":      "security_event",
    "secure_boot_event":    "security_event",
    "info":                 "info_event",
    "separator":            "info_event",
}
# Fallback for any token type not in map: "unknown_event"

_SEVERITY_MAP: dict[str, str] = {
    "kernel_panic":    "critical",
    "gpu_hang":        "critical",
    "memory_fault":    "critical",
    "lockup":          "critical",
    "soc_crash":       "critical",
    "kernel_oops":     "error",
    "gpu_reset":       "error",
    "gpu_timeout":     "error",
    "firmware_fail":   "error",
    "oom_kill":        "error",
    "deadlock":        "error",
    "rcu_stall":       "error",
    "pcie_fault":      "error",
    "smmu_fault":      "error",
    "dma_fault":       "error",
    "power_fault":     "error",
    "remoteproc_fail": "error",
    "storage_fail":    "error",
    "phy_fail":        "error",
    "warning_event":   "warning",
    "security_event":  "warning",
    "hung_task":       "warning",
    "info_event":      "info",
    "unknown_event":   "info",
}


# ── Internal helpers ──────────────────────────────────────────────────────────


def _make_event(
    event_id: int,
    tokens: list[LogToken],
    opening_type: str,
    provider_name: str,
) -> LogEvent:
    """Build a LogEvent from an accumulated token list."""
    if not tokens:
        raise ValueError("Cannot build event from empty token list")
    first = tokens[0]
    event_type = _EVENT_TYPE_MAP.get(opening_type, "unknown_event")
    severity   = _SEVERITY_MAP.get(event_type, "info")
    has_call_trace = any(t.token_type == "call_trace_frame" for t in tokens)
    has_registers  = any(t.token_type in {"register_dump", "register_arm64"} for t in tokens)
    return LogEvent(
        event_id       = event_id,
        event_type     = event_type,
        severity       = severity,
        subsystem      = "unknown",   # assigned by EventClassifier
        ip_block       = "unknown",   # assigned by EventClassifier
        tokens         = list(tokens),
        start_line     = first.line_no,
        end_line       = tokens[-1].line_no,
        arch           = first.arch,
        chip_gen       = first.chip_gen,
        kernel_ver     = first.kernel_ver,
        confidence     = 0.0,         # assigned by EventClassifier
        raw_text       = "\n".join(t.raw for t in tokens),
        has_call_trace = has_call_trace,
        has_registers  = has_registers,
        provider_name  = provider_name,
    )


def _open_event(
    tok: LogToken,
    event_id: int,
    pending_info: list[LogToken],
) -> tuple[list[LogToken], str, int, list[LogToken]]:
    """
    Transition: open a new event starting with tok.
    Clears pending_info_tokens (discarded when a boundary arrives in IDLE).
    Returns (current_tokens, opening_type, last_boundary_line, new_pending).
    """
    return [tok], tok.token_type, tok.line_no, []


# ── Main generator ─────────────────────────────────────────────────────────────


def assemble(
    tokens: Iterator[LogToken],
    *,
    skip_duplicates: bool = True,
    max_event_lines: int  = 200,
    provider: Any         = None,
) -> Iterator[LogEvent]:
    """
    Consume a LogToken stream and yield LogEvent objects.

    Rules (see SPEC_phase3.md §6 for full state machine):
    - BOUNDARY tokens open a new event.
    - CONTINUATION tokens extend the current event.
    - "warning" tokens: open a warning_event from IDLE; in IN_EVENT, they are
      appended if within 5 lines of the last boundary, otherwise close the
      current event and open a new warning_event.
    - INFO tokens between events are buffered and flushed as info_event at
      stream end.
    - Unknown/custom token types: in IDLE → unknown_event; in IN_EVENT → appended.
    - skip_duplicates=True: is_duplicate tokens are dropped before assembly.
    - max_event_lines: force-close at 200 tokens to prevent memory runaway.
    - Empty stream: yields nothing (not an error).
    """
    provider_name: str = provider.name() if provider is not None else "generic"

    # State
    state: _State = _State.IDLE

    event_id:             int         = 0
    current_tokens:       list[LogToken] = []
    opening_type:         str         = ""
    last_boundary_line:   int         = 0
    pending_info_tokens:  list[LogToken] = []

    for tok in tokens:
        # ── Duplicate filter ──────────────────────────────────────────────
        if skip_duplicates and tok.is_duplicate:
            continue

        # ── IDLE state ────────────────────────────────────────────────────
        if state is _State.IDLE:
            if tok.token_type in BOUNDARY_TOKEN_TYPES:
                event_id += 1
                current_tokens, opening_type, last_boundary_line, pending_info_tokens = \
                    _open_event(tok, event_id, pending_info_tokens)
                state = _State.IN_EVENT

            elif tok.token_type == "warning":
                # warning in IDLE: open a warning_event just like a boundary
                event_id += 1
                current_tokens, opening_type, last_boundary_line, pending_info_tokens = \
                    _open_event(tok, event_id, pending_info_tokens)
                state = _State.IN_EVENT

            elif tok.token_type in INFO_TOKEN_TYPES:
                pending_info_tokens.append(tok)

            else:
                # custom / unknown / orphaned continuation token → unknown_event
                event_id += 1
                current_tokens, opening_type, last_boundary_line, pending_info_tokens = \
                    _open_event(tok, event_id, pending_info_tokens)
                state = _State.IN_EVENT

        # ── IN_EVENT state ────────────────────────────────────────────────
        else:
            if tok.token_type in CONTINUATION_TOKEN_TYPES:
                current_tokens.append(tok)

            elif tok.token_type == "warning":
                gap = tok.line_no - last_boundary_line
                if gap <= 5:
                    # close proximity → absorb as continuation
                    current_tokens.append(tok)
                else:
                    # far from boundary → close current, open warning_event
                    yield _make_event(event_id, current_tokens, opening_type, provider_name)
                    event_id += 1
                    current_tokens = [tok]
                    opening_type = tok.token_type
                    last_boundary_line = tok.line_no
                    # state remains IN_EVENT

            elif tok.token_type in BOUNDARY_TOKEN_TYPES:
                # Any non-warning boundary closes current and starts a new event
                yield _make_event(event_id, current_tokens, opening_type, provider_name)
                event_id += 1
                current_tokens = [tok]
                opening_type = tok.token_type
                last_boundary_line = tok.line_no
                # state remains IN_EVENT

            elif tok.token_type in INFO_TOKEN_TYPES:
                gap = tok.line_no - last_boundary_line
                if gap <= 5:
                    # context window → absorb into current event
                    current_tokens.append(tok)
                else:
                    # drift too far → close event, go idle, collect info token
                    yield _make_event(event_id, current_tokens, opening_type, provider_name)
                    current_tokens = []
                    opening_type = ""
                    pending_info_tokens = [tok]
                    state = _State.IDLE

            else:
                # custom / unknown token type → absorb into current event
                current_tokens.append(tok)

            # ── max_event_lines guard (checked after each IN_EVENT append) ─
            if state is _State.IN_EVENT and len(current_tokens) >= max_event_lines:
                yield _make_event(event_id, current_tokens, opening_type, provider_name)
                current_tokens = []
                opening_type = ""
                state = _State.IDLE

    # ── Stream exhausted ──────────────────────────────────────────────────────
    if state is _State.IN_EVENT and current_tokens:
        yield _make_event(event_id, current_tokens, opening_type, provider_name)

    if pending_info_tokens:
        event_id += 1
        yield _make_event(
            event_id, pending_info_tokens,
            pending_info_tokens[0].token_type, provider_name,
        )
