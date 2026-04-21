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


# ── Schema sentinel (used by tests and LLM agent for field discovery) ─────────
# Mirrors exactly what CascadeResult.to_dict() returns.

OUTPUT_SCHEMA: dict = {
    "root_cause": {
        "event_id":   0,
        "event_type": "",
        "subsystem":  "",
        "severity":   "",
        "confidence": 0.0,
        "start_line": 0,
        "end_line":   0,
        "raw_text":   "",
    },
    "cascade": [
        {
            "from":       "",
            "to":         "",
            "relation":   "",
            "confidence": 0.0,
            "reasoning":  "",
        }
    ],
    "summary": {
        "chip_gen":       "",
        "arch":           "",
        "kernel_ver":     None,
        "severity":       "",
        "subsystems_hit": [],
        "event_count":    0,
        "critical_count": 0,
        "error_count":    0,
        "warning_count":  0,
        "info_count":     0,
    },
    "ascii_diagram": "",
}


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


# ── Phase 7 additions ────────────────────────────────────────────────────────

from soctriage.core.agent_result import AgentResult, ToolCall
from soctriage.core.assembler    import LogEvent

OUTPUTSCHEMA: dict = {
    "version":           str,
    "soctriage_version": str,
    "provider":          str,
    "chip_gen":          str,
    "arch":              str,
    "kernel_ver":        str,
    "severity":          str,
    "events":            list,
    "cascade":           dict,
    "ascii_diagram":     str,
    "root_cause":        str,
    "fix":               list,
    "known_issues":      list,
    "confidence":        float,
    "llm_backend":       str,
    "llm_model":         str,
    "tool_trace":        list,
    "hardware":          list,
    "analysis_ms":       int,
}


def report(
    agent_result: "AgentResult",
    *,
    fmt:         str        = "json",
    output:      str | None = None,
    pretty:      bool       = True,
    include_raw: bool       = False,
) -> str:
    """
    Unified report() wrapper — implements the Phase 0 XFAIL-06 stub.
    Returns rendered string. Writes to output path when output is set.
    Never raises — returns minimal error JSON on failure.
    """
    try:
        if fmt == "markdown":
            rendered = _to_markdown(agent_result)
        elif fmt == "html":
            from soctriage.core.html_renderer import render_html
            rendered = render_html(agent_result)
        else:
            rendered = _to_json(agent_result, pretty=pretty, include_raw=include_raw)

        if output:
            with open(output, "w", encoding="utf-8") as fh:
                fh.write(rendered)
        return rendered

    except Exception as exc:
        import json as _json
        return _json.dumps({"error": str(exc), "version": "1.0"}, indent=2)


def _to_json(result: "AgentResult", pretty: bool, include_raw: bool) -> str:
    import json, importlib.metadata
    try:
        soctriage_ver = importlib.metadata.version("soctriage")
    except Exception:
        soctriage_ver = "dev"

    cascade = result.cascade
    doc = {
        "version":           "1.0",
        "soctriage_version": soctriage_ver,
        "provider":          cascade.events[0].provider_name if cascade.events else "generic",
        "chip_gen":          cascade.chip_gen,
        "arch":              cascade.arch,
        "kernel_ver":        cascade.kernel_ver or "unknown",
        "severity":          cascade.severity,
        "events":            [_event_to_dict(e, include_raw) for e in cascade.events],
        "cascade":           cascade.to_dict(),
        "ascii_diagram":     cascade.ascii_diagram,
        "root_cause":        result.root_cause_narrative,
        "fix":               result.fix_suggestions,
        "known_issues":      result.known_issues_matched,
        "confidence":        round(result.confidence, 4),
        "llm_backend":       result.llm_backend,
        "llm_model":         result.llm_model,
        "tool_trace":        [_tool_call_to_dict(tc) for tc in result.tool_trace],
        "hardware": [
            hw.to_dict()
            for e in cascade.events
            for hw in [e.__dict__.get("hardware_context")]
            if hw is not None
        ],
        "analysis_ms": result.total_ms,
    }
    return json.dumps(doc, indent=2 if pretty else None, default=str)


def _to_markdown(result: "AgentResult") -> str:
    cascade = result.cascade
    lines = [
        "# SoCTriage Report",
        "",
        f"**chip_gen:** `{cascade.chip_gen}` | "
        f"**arch:** `{cascade.arch}` | "
        f"**kernel:** `{cascade.kernel_ver or 'unknown'}`",
        f"**Severity:** `{cascade.severity.upper()}`",
        "",
        "---",
        "",
        result.to_markdown(),
    ]
    return "\n".join(lines)


def _event_to_dict(event: "LogEvent", include_raw: bool) -> dict:
    d: dict = {
        "event_id":   event.event_id,
        "event_type": event.event_type,
        "subsystem":  event.subsystem,
        "ip_block":   event.ip_block,
        "severity":   event.severity,
        "confidence": round(event.confidence, 4),
        "start_line": event.start_line,
        "end_line":   event.end_line,
        "chip_gen":   event.chip_gen,
        "arch":       event.arch,
    }
    if include_raw:
        d["raw_text"] = event.raw_text
    return d


def _tool_call_to_dict(tc: "ToolCall") -> dict:
    return {
        "index":       tc.call_index,
        "tool":        tc.tool_name,
        "args":        tc.arguments,
        "duration_ms": tc.duration_ms,
    }
