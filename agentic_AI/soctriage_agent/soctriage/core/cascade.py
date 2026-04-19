"""
cascade.py — Phase 4 v4.0.0

CascadeAnalyzer: transforms a classified list[LogEvent] into a CascadeResult.

Public symbols: CascadeEdge, CascadeResult, analyse()

Note: ascii_diagram rendering is intentionally NOT done inside analyse() to
avoid a circular import (ascii_diagram.py imports from this module).
Callers should run:
    result = analyse(events, ...)
    result.ascii_diagram = render(result)   # from soctriage.core.ascii_diagram
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

from soctriage.core.assembler import LogEvent

__all__ = [
    "CascadeEdge", "CascadeResult", "analyse",
    "_break_cycles", "_has_cycle", "_get_provider_rules",
]

logger = logging.getLogger(__name__)

# ── Confidence formula constants ──────────────────────────────────────────────

_RC_BASE_CONF:        float = 0.4   # root-cause base confidence
_RC_EDGE_BONUS:       float = 0.1   # per outgoing "causes" edge
_RC_EVENT_CONF_WEIGHT: float = 0.3  # weight of event.confidence in root-cause score


# ── Causal edge ───────────────────────────────────────────────────────────────


@dataclass
class CascadeEdge:
    source_id:  int
    target_id:  int
    relation:   str    # "causes" | "precedes" | "correlates" | "masks" (reserved — no rules use "masks" yet)
    confidence: float  # 0.0–1.0
    reasoning:  str    # one-line human-readable reason


# ── Cascade result ────────────────────────────────────────────────────────────


@dataclass
class CascadeResult:
    events:          list[LogEvent]
    edges:           list[CascadeEdge]
    root_cause_id:   int | None
    root_cause_conf: float
    severity:        str
    subsystems_hit:  list[str]
    chip_gen:        str
    arch:            str
    kernel_ver:      str | None
    ascii_diagram:   str
    event_count:     int
    critical_count:  int
    error_count:     int
    analysis_ns:     int
    warning_count:   int = 0
    info_count:      int = 0

    def to_dict(self) -> dict:
        """Serialise to JSON-compatible dict for LLM agent tool response."""
        ev_map = {e.event_id: e for e in self.events}
        root_cause_dict = None
        if self.root_cause_id is not None and self.root_cause_id in ev_map:
            rc = ev_map[self.root_cause_id]
            root_cause_dict = {
                "event_id":   rc.event_id,
                "event_type": rc.event_type,
                "subsystem":  rc.subsystem,
                "severity":   rc.severity,
                "confidence": round(self.root_cause_conf, 4),
                "start_line": rc.start_line,
                "end_line":   rc.end_line,
                "raw_text":   rc.raw_text,
            }
        cascade_list = []
        for edge in self.edges:
            src = ev_map.get(edge.source_id)
            tgt = ev_map.get(edge.target_id)
            cascade_list.append({
                "from":       src.event_type if src else str(edge.source_id),
                "to":         tgt.event_type if tgt else str(edge.target_id),
                "relation":   edge.relation,
                "confidence": round(edge.confidence, 4),
                "reasoning":  edge.reasoning,
            })
        return {
            "root_cause": root_cause_dict,
            "cascade": cascade_list,
            "summary": {
                "chip_gen":       self.chip_gen,
                "arch":           self.arch,
                "kernel_ver":     self.kernel_ver,
                "severity":       self.severity,
                "subsystems_hit": self.subsystems_hit,
                "event_count":    self.event_count,
                "critical_count": self.critical_count,
                "error_count":    self.error_count,
                "warning_count":  self.warning_count,
                "info_count":     self.info_count,
            },
            "ascii_diagram": self.ascii_diagram,
        }

    def summary(self) -> str:
        """One-paragraph plain-text summary ≤ 500 chars for LLM agent context."""
        rc_desc = "none"
        if self.root_cause_id is not None:
            ev_map = {e.event_id: e for e in self.events}
            rc = ev_map.get(self.root_cause_id)
            if rc:
                rc_desc = (
                    f"{rc.event_type} in {rc.subsystem}"
                    f" (conf={self.root_cause_conf:.2f})"
                )
        subsys = ", ".join(self.subsystems_hit) or "unknown"
        kver = self.kernel_ver or "unknown"
        text = (
            f"SoCTriage analysis of {self.chip_gen} ({self.arch}, kernel {kver}): "
            f"{self.event_count} events "
            f"({self.critical_count} critical, {self.error_count} error). "
            f"Root cause: {rc_desc}. "
            f"Severity: {self.severity.upper()}. "
            f"Subsystems: {subsys}."
        )
        return text[:500]


# ── Rule representation ───────────────────────────────────────────────────────


class _Rule(NamedTuple):
    source:     str    # event_type of cause; "*" = any
    target:     str    # event_type of effect; "*" = any
    relation:   str
    confidence: float
    reasoning:  str


# ── Core cascade rules (CR-01 … CR-30) ───────────────────────────────────────
# Uses event_type names from assembler._EVENT_TYPE_MAP.
# "pcie_fault" is the event_type produced from "pcie_error" token_type.

_CORE_RULES: list[_Rule] = [
    # CR-01
    _Rule("smmu_fault",      "gpu_hang",        "causes",     0.85,
          "SMMU blocking GPU DMA → ring timeout"),
    # CR-02
    _Rule("smmu_fault",      "kernel_panic",    "causes",     0.80,
          "IOMMU fault with no handler → panic"),
    # CR-03
    _Rule("pcie_fault",      "gpu_hang",        "causes",     0.80,
          "PCIe link error → GPU loses MMIO access"),
    # CR-04
    _Rule("pcie_fault",      "smmu_fault",      "precedes",   0.60,
          "PCIe fault can trigger SMMU re-mapping failure"),
    # CR-05
    _Rule("gpu_hang",        "kernel_panic",    "causes",     0.75,
          "GPU hang with no recovery → kernel panic"),
    # CR-06
    _Rule("gpu_hang",        "oom_kill",        "precedes",   0.50,
          "GPU hang can hold GEM buffers → OOM pressure"),
    # CR-07
    _Rule("firmware_fail",   "gpu_hang",        "causes",     0.90,
          "GuC/HuC firmware not loaded → ring timeout"),
    # CR-08
    _Rule("firmware_fail",   "kernel_panic",    "causes",     0.85,
          "PSP/ABL failure → unrecoverable boot panic"),
    # CR-09
    _Rule("memory_fault",    "kernel_panic",    "causes",     0.90,
          "UAF/null deref → panic"),
    # CR-10
    _Rule("memory_fault",    "gpu_hang",        "precedes",   0.55,
          "Memory corruption can poison GPU command buffer"),
    # CR-11
    _Rule("oom_kill",        "kernel_panic",    "precedes",   0.40,
          "OOM kill of critical process → panic"),
    # CR-12
    _Rule("lockup",          "kernel_panic",    "causes",     0.95,
          "Hard lockup with NMI watchdog → panic"),
    # CR-13
    _Rule("deadlock",        "lockup",          "causes",     0.70,
          "Locking deadlock → soft lockup → watchdog"),
    # CR-14
    _Rule("rcu_stall",       "lockup",          "causes",     0.65,
          "RCU stall → soft lockup"),
    # CR-15
    _Rule("power_fault",     "gpu_hang",        "causes",     0.75,
          "Under-voltage / clk failure → GPU ring timeout"),
    # CR-16
    _Rule("power_fault",     "kernel_panic",    "causes",     0.70,
          "Thermal shutdown → panic"),
    # CR-17
    _Rule("soc_crash",       "kernel_panic",    "causes",     0.90,
          "ADSP/CDSP crash → remoteproc panic path"),
    # CR-18
    _Rule("soc_crash",       "remoteproc_fail", "causes",     0.85,
          "PD crash → remoteproc failure"),
    # CR-19
    _Rule("remoteproc_fail", "kernel_panic",    "precedes",   0.60,
          "DSP fail → kernel may panic if service critical"),
    # CR-20
    _Rule("dma_fault",       "gpu_hang",        "causes",     0.80,
          "DMA engine failure → GPU stall"),
    # CR-21
    _Rule("dma_fault",       "smmu_fault",      "correlates", 0.65,
          "DMA out-of-bounds → SMMU fault"),
    # CR-22
    _Rule("storage_fail",    "oom_kill",        "precedes",   0.45,
          "I/O error → blk queue fill → memory pressure"),
    # CR-23
    _Rule("phy_fail",        "pcie_fault",      "causes",     0.80,
          "PHY cal failure → PCIe link down"),
    # CR-24
    _Rule("phy_fail",        "smmu_fault",      "precedes",   0.50,
          "PHY reset → transient IOMMU remapping"),
    # CR-25
    _Rule("gpu_hang",        "gpu_reset",       "causes",     0.95,
          "Hang triggers reset attempt"),
    # CR-26
    _Rule("gpu_reset",       "kernel_panic",    "precedes",   0.55,
          "Failed reset → panic"),
    # CR-27
    _Rule("mce_error",       "memory_fault",    "causes",     0.85,
          "Machine check → memory poisoning"),
    # CR-28
    _Rule("mce_error",       "kernel_panic",    "causes",     0.90,
          "Uncorrectable MCE → panic"),
    # CR-29
    _Rule("security_event",  "kernel_panic",    "precedes",   0.35,
          "Lockdown violation can trigger panic"),
    # CR-30 (wildcard — target="*")
    _Rule("warning_event",   "*",               "precedes",   0.20,
          "Warnings often precede harder failures"),
]


# ── Provider-specific rules ───────────────────────────────────────────────────

# Intel — CI-01 (higher confidence override), CI-02, CI-03
_INTEL_RULES: list[_Rule] = [
    _Rule("firmware_fail",   "gpu_hang",        "causes",     0.95,
          "GuC submission engine offline → all rings timeout"),
    _Rule("pcie_fault",      "gpu_hang",        "causes",     0.90,
          "i915 PCIe reset → GTT mapping lost"),
]

# AMD — CA-01 (higher confidence override), CA-02, CA-03, CA-04
_AMD_RULES: list[_Rule] = [
    _Rule("firmware_fail",   "kernel_panic",    "causes",     0.95,
          "AMD PSP init failure → unrecoverable"),
    _Rule("smmu_fault",      "gpu_hang",        "causes",     0.90,
          "AMD IOMMU v2 fault → GFXHUB stall"),
    _Rule("memory_fault",    "gpu_hang",        "causes",     0.80,
          "VRAM ECC error → amdgpu ring reset"),
    _Rule("power_fault",     "gpu_hang",        "causes",     0.85,
          "PMFW voltage fail → GFX power gating"),
]

# Qualcomm — CQ-01, CQ-02, CQ-03, CQ-04
_QCOM_RULES: list[_Rule] = [
    _Rule("soc_crash",       "kernel_panic",    "causes",     0.90,
          "ADSP crash with SMP2P notify → kernel panic"),
    _Rule("power_fault",     "soc_crash",       "causes",     0.85,
          "RPMh power collapse → DSP power domain off"),
    _Rule("smmu_fault",      "soc_crash",       "precedes",   0.65,
          "SMMU context fault → PIL reload fail"),
    _Rule("phy_fail",        "storage_fail",    "causes",     0.80,
          "UFS PHY failure → UFS link down"),
]

# NVIDIA — CN-01, CN-02
_NVIDIA_RULES: list[_Rule] = [
    _Rule("firmware_fail",   "gpu_hang",        "causes",     0.90,
          "GSP firmware fail → all NVKM channels dead"),
    _Rule("pcie_fault",      "gpu_hang",        "causes",     0.85,
          "PCIe link width drop → BAR access fail"),
]


def _get_provider_rules(chip_gen: str) -> list[_Rule]:
    """Return provider-specific rules based on chip_gen prefix."""
    cg = chip_gen.lower()
    if cg.startswith("intel_"):
        return _INTEL_RULES
    if cg.startswith("amd_"):
        return _AMD_RULES
    if cg.startswith("qcom_"):
        return _QCOM_RULES
    if cg.startswith("nvidia_"):
        return _NVIDIA_RULES
    return []


# ── Event deduplication ───────────────────────────────────────────────────────


def _deduplicate_events(events: list[LogEvent]) -> list[LogEvent]:
    """
    Remove events with the same (event_type, subsystem) within 10 lines of the
    most recently kept event of that type+subsystem pair.  O(n) — events are
    assumed to be in log order (monotonically increasing start_line).
    """
    last_kept_line: dict[tuple[str, str], int] = {}
    result: list[LogEvent] = []
    for ev in events:
        key = (ev.event_type, ev.subsystem)
        last_line = last_kept_line.get(key)
        if last_line is None or ev.start_line - last_line > 10:
            result.append(ev)
            last_kept_line[key] = ev.start_line
    return result


# ── Edge building ─────────────────────────────────────────────────────────────


def _build_edges(
    events: list[LogEvent],
    rules: list[_Rule],
    *,
    max_edges: int,
    min_confidence: float,
) -> list[CascadeEdge]:
    """Build causal edges between events using the combined rule table."""
    if not events:
        return []

    # Separate exact rules from wildcard rules, respecting "first match wins"
    # (provider rules come first in the combined list, so they take priority).
    exact_lookup: dict[tuple[str, str], _Rule] = {}
    wildcard_by_source: dict[str, _Rule] = {}

    for rule in rules:
        if rule.confidence < min_confidence:
            continue
        if rule.target == "*":
            # Keep highest-confidence wildcard per source type
            prev = wildcard_by_source.get(rule.source)
            if prev is None or rule.confidence > prev.confidence:
                wildcard_by_source[rule.source] = rule
        else:
            key = (rule.source, rule.target)
            if key not in exact_lookup:
                exact_lookup[key] = rule

    # Group events by type for O(distinct_types) iteration instead of O(n²)
    by_type: dict[str, list[LogEvent]] = defaultdict(list)
    for ev in events:
        by_type[ev.event_type].append(ev)

    edges: list[CascadeEdge] = []
    edge_pairs: set[tuple[int, int]] = set()

    def _add(src_ev: LogEvent, tgt_ev: LogEvent, rule: _Rule) -> bool:
        """Add edge; return True if max_edges reached."""
        pair = (src_ev.event_id, tgt_ev.event_id)
        if pair in edge_pairs:
            return False
        edges.append(CascadeEdge(
            source_id=src_ev.event_id,
            target_id=tgt_ev.event_id,
            relation=rule.relation,
            confidence=rule.confidence,
            reasoning=rule.reasoning,
        ))
        edge_pairs.add(pair)
        return len(edges) >= max_edges

    # Exact rules
    for (src_type, tgt_type), rule in exact_lookup.items():
        for src_ev in by_type.get(src_type, []):
            for tgt_ev in by_type.get(tgt_type, []):
                if tgt_ev.event_id > src_ev.event_id:
                    if _add(src_ev, tgt_ev, rule):
                        return edges

    # Wildcard rules (warning_event → any): add early exit at the source level
    # to avoid iterating over all targets once the edge cap is reached.
    for src_type, rule in wildcard_by_source.items():
        for src_ev in by_type.get(src_type, []):
            if len(edges) >= max_edges:
                return edges
            for tgt_ev in events:
                if tgt_ev.event_id > src_ev.event_id and tgt_ev.event_type != src_type:
                    if _add(src_ev, tgt_ev, rule):
                        return edges

    return edges


# ── Cycle detection and breaking ──────────────────────────────────────────────


def _has_cycle(adj: dict[int, list[int]], nodes: list[int]) -> bool:
    """Return True if the directed graph has any cycle (iterative DFS)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {n: WHITE for n in nodes}

    def dfs(start: int) -> bool:
        stack = [(start, iter(adj.get(start, [])))]
        color[start] = GRAY
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if color.get(child, WHITE) == GRAY:
                    return True
                if color.get(child, WHITE) == WHITE:
                    color[child] = GRAY
                    stack.append((child, iter(adj.get(child, []))))
            except StopIteration:
                color[node] = BLACK
                stack.pop()
        return False

    for node in nodes:
        if color.get(node, WHITE) == WHITE:
            if dfs(node):
                return True
    return False


def _break_cycles(edges: list[CascadeEdge], event_ids: list[int]) -> list[CascadeEdge]:
    """Remove lowest-confidence edges until the graph is acyclic."""
    working = list(edges)
    max_iters = len(working) + 1

    for _ in range(max_iters):
        adj: dict[int, list[int]] = defaultdict(list)
        for e in working:
            adj[e.source_id].append(e.target_id)

        if not _has_cycle(adj, event_ids):
            break

        # Remove the lowest-confidence edge (stable: also prefer later source_id for ties)
        min_edge = min(working, key=lambda e: (e.confidence, -e.source_id))
        logger.warning(
            "Cascade cycle detected — removing edge %d→%d (conf=%.2f, relation=%s)",
            min_edge.source_id, min_edge.target_id,
            min_edge.confidence, min_edge.relation,
        )
        working.remove(min_edge)

    return working


# ── Root cause identification ─────────────────────────────────────────────────


def _find_root_cause(
    events: list[LogEvent],
    edges:  list[CascadeEdge],
) -> tuple[int | None, float]:
    """
    Root cause = event with most outgoing causes edges, earliest in log,
    severity >= error, and not a high-confidence downstream target.

    Returns (event_id, confidence) or (None, 0.0) for empty input.
    """
    if not events:
        return None, 0.0

    out_edges: dict[int, list[CascadeEdge]] = defaultdict(list)
    in_causes: dict[int, list[CascadeEdge]] = defaultdict(list)
    for edge in edges:
        out_edges[edge.source_id].append(edge)
        if edge.relation == "causes" and edge.confidence > 0.7:
            in_causes[edge.target_id].append(edge)

    severity_rank = {"critical": 3, "error": 2, "warning": 1, "info": 0}
    candidates = [
        e for e in events
        if severity_rank.get(e.severity, 0) >= 2
        and e.event_id not in in_causes
    ]
    if not candidates:
        candidates = events  # fallback: all events

    def score(e: LogEvent) -> tuple:
        causes_count = sum(1 for ed in out_edges[e.event_id] if ed.relation == "causes")
        return (causes_count, -e.start_line, e.confidence)

    best = max(candidates, key=score)
    out_degree = sum(1 for ed in out_edges[best.event_id] if ed.relation == "causes")
    conf = min(1.0, _RC_BASE_CONF + _RC_EDGE_BONUS * out_degree + best.confidence * _RC_EVENT_CONF_WEIGHT)
    return best.event_id, conf



# ── Phase 3c hardware context enrichment ─────────────────────────────────────


def _hw_confidence_boost(events: list[LogEvent]) -> dict[tuple[str, str], float]:
    """
    Return (source_event_type, target_event_type) → confidence_boost derived
    from hardware_context signals attached by Phase 3c decode_hardware().
    Advisory enrichment only — empty dict when no events carry hardware_context.
    """
    boosts: dict[tuple[str, str], float] = {}
    for ev in events:
        hw_ctx = ev.__dict__.get("hardware_context")
        if hw_ctx is None:
            continue
        stall_type = getattr(hw_ctx, "stall_type", None)
        if stall_type == "firmware_boot_fail":
            key = ("firmware_fail", "gpu_hang")
            boosts[key] = min(0.15, boosts.get(key, 0.0) + 0.05)
        elif stall_type == "memory_translation_fault":
            key = ("smmu_fault", "gpu_hang")
            boosts[key] = min(0.15, boosts.get(key, 0.0) + 0.05)
        elif stall_type == "firmware_runtime_crash":
            key = ("soc_crash", "kernel_panic")
            boosts[key] = min(0.15, boosts.get(key, 0.0) + 0.05)
    return boosts


def _apply_hw_boosts(
    edges: list[CascadeEdge],
    events: list[LogEvent],
    boosts: dict[tuple[str, str], float],
) -> list[CascadeEdge]:
    """Apply hardware context confidence boosts to matching edges."""
    if not boosts:
        return edges
    ev_map = {e.event_id: e for e in events}
    for edge in edges:
        src = ev_map.get(edge.source_id)
        tgt = ev_map.get(edge.target_id)
        if src is None or tgt is None:
            continue
        boost = boosts.get((src.event_type, tgt.event_type), 0.0)
        if boost > 0.0:
            edge.confidence = min(1.0, edge.confidence + boost)
    return edges


# ── Main entry point ──────────────────────────────────────────────────────────


def analyse(
    events: list[LogEvent],
    *,
    max_edges:          int   = 500,
    min_confidence:     float = 0.15,
    use_provider_rules: bool  = False,
) -> CascadeResult:
    """
    Analyse a list of classified LogEvents and produce a CascadeResult.

    Steps:
    1. Deduplicate events (same event_type + subsystem within 10 lines)
    2. Build causal edges using rule table (provider-specific + core)
    3. Prune edges below min_confidence
    4. Detect cycles — break by removing lowest-confidence edge
    5. Identify root cause
    6. Populate and return CascadeResult (ascii_diagram left empty — caller fills it)

    Empty list → CascadeResult with no edges, root_cause_id=None.
    Single event → root cause is that event, no edges.
    Completes in < 500ms for up to 10,000 events.
    """
    t0 = time.perf_counter_ns()

    # 1. Deduplicate
    deduped = _deduplicate_events(list(events))

    # 2. Determine chip_gen from events (for provider rule selection)
    chip_gen = "unknown"
    for ev in deduped:
        if ev.chip_gen != "unknown":
            chip_gen = ev.chip_gen
            break

    # Combine rules: provider-specific first (higher priority), then core.
    # Provider rules are selected by chip_gen prefix, not by a provider object.
    prov_rules = _get_provider_rules(chip_gen) if use_provider_rules else []

    combined_rules = prov_rules + _CORE_RULES

    # 3. Build edges (min_confidence filtering happens inside)
    edges = _build_edges(deduped, combined_rules, max_edges=max_edges, min_confidence=min_confidence)

    # 3b. Apply Phase 3c hardware context confidence boosts (advisory, no-op if absent)
    hw_boosts = _hw_confidence_boost(deduped)
    if hw_boosts:
        edges = _apply_hw_boosts(edges, deduped, hw_boosts)

    # 4. Break cycles
    event_ids = [ev.event_id for ev in deduped]
    edges = _break_cycles(edges, event_ids)

    # 5. Find root cause
    root_cause_id, root_cause_conf = _find_root_cause(deduped, edges)

    # 6. Aggregate fields
    severity_rank = {"critical": 3, "error": 2, "warning": 1, "info": 0}
    severity = "info"
    for ev in deduped:
        if severity_rank.get(ev.severity, 0) > severity_rank.get(severity, 0):
            severity = ev.severity

    seen_subsys: set[str] = set()
    subsystems_hit: list[str] = []
    for ev in deduped:
        if ev.subsystem not in seen_subsys:
            seen_subsys.add(ev.subsystem)
            subsystems_hit.append(ev.subsystem)

    arch = "unknown"
    kernel_ver: str | None = None
    for ev in deduped:
        if ev.arch != "unknown":
            arch = ev.arch
            break
    for ev in deduped:
        if ev.kernel_ver is not None:
            kernel_ver = ev.kernel_ver
            break

    critical_count = sum(1 for ev in deduped if ev.severity == "critical")
    error_count    = sum(1 for ev in deduped if ev.severity == "error")
    warning_count  = sum(1 for ev in deduped if ev.severity == "warning")
    info_count     = sum(1 for ev in deduped if ev.severity == "info")

    result = CascadeResult(
        events=deduped,
        edges=edges,
        root_cause_id=root_cause_id,
        root_cause_conf=root_cause_conf,
        severity=severity,
        subsystems_hit=subsystems_hit,
        chip_gen=chip_gen,
        arch=arch,
        kernel_ver=kernel_ver,
        ascii_diagram="",   # caller is responsible for populating via ascii_diagram.render()
        event_count=len(deduped),
        critical_count=critical_count,
        error_count=error_count,
        analysis_ns=time.perf_counter_ns() - t0,
        warning_count=warning_count,
        info_count=info_count,
    )

    return result
