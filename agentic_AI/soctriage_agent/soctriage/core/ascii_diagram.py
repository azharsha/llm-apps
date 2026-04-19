"""
ascii_diagram.py — Phase 4 v4.0.0

Renders a CascadeResult as a plain-text ASCII cascade diagram.

Public symbols: render()
No external dependencies — stdlib only.
"""

from __future__ import annotations

from collections import defaultdict, deque

from soctriage.core.cascade import CascadeEdge, CascadeResult
from soctriage.core.assembler import LogEvent

__all__ = ["render"]

# Box width (interior = 58 chars between the two │ characters)
_BOX_WIDTH = 60


def _topological_order(
    events: list[LogEvent],
    edges: list[CascadeEdge],
) -> list[LogEvent]:
    """
    Return events in topological order (sources before targets).
    Nodes with no incoming causes/precedes edges are processed first,
    ordered by start_line.  Remaining events are appended at the end.
    """
    adj: dict[int, list[int]] = defaultdict(list)
    in_degree: dict[int, int] = {ev.event_id: 0 for ev in events}

    for edge in edges:
        if edge.relation in ("causes", "precedes"):
            adj[edge.source_id].append(edge.target_id)
            in_degree[edge.target_id] = in_degree.get(edge.target_id, 0) + 1

    # Kahn's algorithm — break ties by start_line
    queue: deque[int] = deque(
        ev.event_id
        for ev in sorted(events, key=lambda e: e.start_line)
        if in_degree.get(ev.event_id, 0) == 0
    )

    ev_map = {ev.event_id: ev for ev in events}
    order: list[LogEvent] = []
    visited: set[int] = set()

    while queue:
        eid = queue.popleft()
        if eid in visited:
            continue
        visited.add(eid)
        if eid in ev_map:
            order.append(ev_map[eid])
        for nxt in sorted(adj[eid]):
            in_degree[nxt] = max(0, in_degree.get(nxt, 0) - 1)
            if in_degree[nxt] == 0 and nxt not in visited:
                queue.append(nxt)

    # Append disconnected events in their original log order (preserved from analyse())
    for ev in events:
        if ev.event_id not in visited:
            order.append(ev)

    return order


def render(result: CascadeResult) -> str:
    """
    Render a CascadeResult as a plain-text ASCII cascade diagram.

    Returns a multi-line string.  Uses Unicode box-drawing characters.
    All lines are under 80 characters.  No colour codes.
    Safe to call on an empty CascadeResult (zero events).
    """
    lines: list[str] = []

    # ── Header box ────────────────────────────────────────────────────────
    chip = result.chip_gen  or "unknown"
    arch = result.arch      or "unknown"
    kver = result.kernel_ver or "unknown"

    top    = "╔" + "═" * 58 + "╗"
    title  = "║" + "SoCTriage Cascade Analysis".center(58) + "║"
    # keep the info line ≤ 60 chars total (box chars inclusive)
    info_inner = f"  chip: {chip:<10}  arch: {arch:<7}  kernel: {kver:<10}"
    info_inner = info_inner[:58]
    info_inner = info_inner.ljust(58)
    info   = "║" + info_inner + "║"
    bottom = "╚" + "═" * 58 + "╝"

    lines += [top, title, info, bottom, ""]

    # ── Event chain ───────────────────────────────────────────────────────
    if not result.events:
        lines.append("  (no events)")
    else:
        ordered = _topological_order(result.events, result.edges)

        # Build per-source best outgoing edge for connectors
        edge_map: dict[int, CascadeEdge] = {}
        for edge in result.edges:
            if edge.relation in ("causes", "precedes"):
                prev = edge_map.get(edge.source_id)
                if prev is None or edge.confidence > prev.confidence:
                    edge_map[edge.source_id] = edge

        for ev in ordered:
            is_root = ev.event_id == result.root_cause_id
            tag = "← ROOT CAUSE" if is_root else ""
            # Truncate fields so the line stays under 80 chars regardless of event_id length
            event_type_str = ev.event_type[:18]
            subsystem_str  = ev.subsystem[:12]
            body = (
                f"  [E{ev.event_id}] {event_type_str:<18}"
                f" subsystem={subsystem_str:<12} conf={ev.confidence:.2f}"
            )
            line = f"{body[:65]}  {tag}" if tag else body
            lines.append(line)
            lines.append(
                f"       lines {ev.start_line}–{ev.end_line:<6}"
                f" severity={ev.severity.upper()}"
            )

            if ev.event_id in edge_map:
                edge = edge_map[ev.event_id]
                reason = edge.reasoning[:45]
                lines.append("       │")
                lines.append(
                    f"       │ {edge.relation} ({edge.confidence:.2f})"
                    f" — {reason}"
                )
                lines.append("       ▼")

    # ── Footer summary ────────────────────────────────────────────────────
    sep = "  " + "─" * 57

    ev_map = {e.event_id: e for e in result.events}
    if result.root_cause_id is not None and result.root_cause_id in ev_map:
        rc_type = ev_map[result.root_cause_id].event_type
        rc_line = (
            f"  Root Cause : [E{result.root_cause_id}] {rc_type}"
            f"  (conf={result.root_cause_conf:.2f})"
        )
    else:
        rc_line = "  Root Cause : none"

    subsys_chain = " → ".join(result.subsystems_hit) or "none"
    # Cap subsystem chain to keep footer line ≤ 79 chars ("  Subsystems : " = 16 chars)
    if len(subsys_chain) > 62:
        subsys_chain = subsys_chain[:61] + "…"

    lines += [
        "",
        sep,
        rc_line,
        f"  Severity   : {result.severity.upper()}",
        f"  Subsystems : {subsys_chain}",
        f"  Events     : {result.event_count} total"
        f"  ({result.critical_count} critical"
        f" · {result.error_count} error"
        f" · {result.warning_count} warning)",
        sep,
    ]

    return "\n".join(lines)
