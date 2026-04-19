"""
reporter.py — Phase 5

Output formatting for SoCTriage analysis results.
Provides render_json() and render_markdown() over a CascadeResult.
"""

from __future__ import annotations

import json
from typing import Optional, TypedDict


# ── Output schema (TypedDict) ─────────────────────────────────────────────────

class EventReport(TypedDict):
    event_id:    int
    event_type:  str
    severity:    str
    subsystem:   str
    ip_block:    str
    start_line:  int
    end_line:    int
    confidence:  float
    provider:    str


class CascadeEntry(TypedDict):
    from_event:  str
    to_event:    str
    relation:    str
    confidence:  float
    reasoning:   str


class RootCauseReport(TypedDict):
    event_id:    int
    event_type:  str
    subsystem:   str
    severity:    str
    confidence:  float
    start_line:  int
    end_line:    int
    raw_text:    str


class AnalysisReport(TypedDict):
    kernel_version:   Optional[str]
    architecture:     str
    asic_generation:  str
    soc_provider:     str
    total_events:     int
    critical_count:   int
    error_count:      int
    severity:         str
    root_cause:       Optional[RootCauseReport]
    cascade:          list[CascadeEntry]
    events:           list[EventReport]
    ascii_diagram:    str


# ── Rendering ─────────────────────────────────────────────────────────────────


def render_json(result: "CascadeResult") -> str:  # type: ignore[name-defined]
    """Serialise a CascadeResult to a JSON string (indented, UTF-8 safe)."""
    # CascadeResult.to_dict() already produces a JSON-compatible dict.
    data = result.to_dict()
    return json.dumps(data, indent=2, ensure_ascii=False)


def render_markdown(result: "CascadeResult") -> str:  # type: ignore[name-defined]
    """Render a CascadeResult as a Markdown report string."""
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines.append("# SoCTriage Analysis Report")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Architecture | `{result.arch}` |")
    lines.append(f"| Chip generation | `{result.chip_gen}` |")
    lines.append(f"| Kernel version | `{result.kernel_ver or 'unknown'}` |")
    lines.append(f"| Overall severity | **{result.severity.upper()}** |")
    lines.append(f"| Total events | {result.event_count} |")
    lines.append(f"| Critical | {result.critical_count} |")
    lines.append(f"| Error | {result.error_count} |")
    lines.append("")

    # ── Root cause ────────────────────────────────────────────────────────
    lines.append("## Root Cause")
    lines.append("")
    if result.root_cause_id is not None:
        ev_map = {e.event_id: e for e in result.events}
        rc = ev_map.get(result.root_cause_id)
        if rc:
            lines.append(f"- **Event type:** `{rc.event_type}`")
            lines.append(f"- **Subsystem:** `{rc.subsystem}`")
            lines.append(f"- **Severity:** `{rc.severity}`")
            lines.append(f"- **Confidence:** {result.root_cause_conf:.2f}")
            lines.append(f"- **Log lines:** {rc.start_line}–{rc.end_line}")
    else:
        lines.append("_No root cause identified._")
    lines.append("")

    # ── Cascade chain ─────────────────────────────────────────────────────
    if result.edges:
        lines.append("## Cascade Chain")
        lines.append("")
        lines.append("| From | To | Relation | Confidence | Reasoning |")
        lines.append("|---|---|---|---|---|")
        ev_map = {e.event_id: e for e in result.events}
        for edge in result.edges:
            src = ev_map.get(edge.source_id)
            tgt = ev_map.get(edge.target_id)
            from_str = src.event_type if src else str(edge.source_id)
            to_str   = tgt.event_type if tgt else str(edge.target_id)
            lines.append(
                f"| `{from_str}` | `{to_str}` | {edge.relation} "
                f"| {edge.confidence:.2f} | {edge.reasoning} |"
            )
        lines.append("")

    # ── Subsystem summary ─────────────────────────────────────────────────
    if result.subsystems_hit:
        lines.append("## Subsystems Hit")
        lines.append("")
        lines.append(" → ".join(f"`{s}`" for s in result.subsystems_hit))
        lines.append("")

    # ── Events table ──────────────────────────────────────────────────────
    if result.events:
        lines.append("## Events")
        lines.append("")
        lines.append("| # | Type | Severity | Subsystem | Lines | Conf |")
        lines.append("|---|---|---|---|---|---|")
        for ev in result.events:
            lines.append(
                f"| {ev.event_id} | `{ev.event_type}` | {ev.severity} "
                f"| {ev.subsystem} | {ev.start_line}–{ev.end_line} "
                f"| {ev.confidence:.2f} |"
            )
        lines.append("")

    # ── ASCII diagram ─────────────────────────────────────────────────────
    if result.ascii_diagram:
        lines.append("## Cascade Diagram")
        lines.append("")
        lines.append("```")
        lines.append(result.ascii_diagram)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)
