"""
tool_registry.py — Phase 6 v6.0.0

Tool definitions and ToolRegistry for the SoCTriageAgent.
All 10 tools are pure Python functions — no LLM or network required.

Public symbols: AgentContext, Tool, ToolRegistry, SUBSYSTEM_ENUM
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from soctriage.core.cascade import CascadeResult

__all__ = ["AgentContext", "Tool", "ToolRegistry", "SUBSYSTEM_ENUM"]


SUBSYSTEM_ENUM: list[str] = [
    "gpu", "memory", "cpu", "firmware", "power",
    "interconnect", "storage", "display", "network",
    "soc_platform", "remoteproc", "security", "virt", "debug", "unknown",
]


@dataclass
class AgentContext:
    cascade:  "CascadeResult"
    provider: Any = None   # SoCProvider | None


@dataclass
class Tool:
    name:        str
    description: str
    parameters:  dict        # JSON Schema "properties" dict
    fn:          Callable    # fn(ctx, **kwargs) -> dict | list | str

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type":       "object",
                    "properties": self.parameters,
                    "required":   list(self.parameters.keys()),
                },
            },
        }


# ── Tool implementations ──────────────────────────────────────────────────────


def _get_event_detail(ctx: AgentContext, event_id: int) -> dict:
    ev_map = {e.event_id: e for e in ctx.cascade.events}
    ev = ev_map.get(event_id)
    if not ev:
        return {"error": f"event_id {event_id} not found"}
    return {
        "event_id":         ev.event_id,
        "event_type":       ev.event_type,
        "subsystem":        ev.subsystem,
        "ip_block":         ev.ip_block,
        "severity":         ev.severity,
        "start_line":       ev.start_line,
        "end_line":         ev.end_line,
        "token_types":      list({t.token_type for t in ev.tokens}),
        "raw_text_excerpt": ev.raw_text[:800],
    }


def _get_known_issues(ctx: AgentContext) -> dict:
    if ctx.provider is None:
        return {"matched": [], "note": "no provider detected"}
    event_types = list({e.event_type for e in ctx.cascade.events})
    # Use get_known_issues() — the actual non-ABC method on each provider
    matched = ctx.provider.get_known_issues(ctx.cascade.chip_gen, event_types)
    return {"matched": matched, "chip_gen": ctx.cascade.chip_gen}


def _get_subsystem_events(ctx: AgentContext, subsystem: str) -> list:
    return [
        {
            "event_id":   e.event_id,
            "event_type": e.event_type,
            "severity":   e.severity,
            "ip_block":   e.ip_block,
        }
        for e in ctx.cascade.events if e.subsystem == subsystem
    ]


def _get_call_trace(ctx: AgentContext, event_id: int) -> dict:
    ev_map = {e.event_id: e for e in ctx.cascade.events}
    ev = ev_map.get(event_id)
    if not ev:
        return {"error": f"event_id {event_id} not found"}
    frames = [t.raw for t in ev.tokens if t.token_type == "call_trace_frame"]
    return {"event_id": event_id, "frames": frames, "count": len(frames)}


def _build_tools() -> list[Tool]:
    return [
        Tool(
            "get_root_cause",
            "Returns the root cause event from cascade analysis.",
            {},
            lambda ctx: ctx.cascade.to_dict()["root_cause"],
        ),
        Tool(
            "get_cascade_chain",
            "Returns the full ordered list of causal edges.",
            {},
            lambda ctx: ctx.cascade.to_dict()["cascade"],
        ),
        Tool(
            "get_ascii_diagram",
            "Returns the ASCII cascade diagram string.",
            {},
            lambda ctx: ctx.cascade.ascii_diagram,
        ),
        Tool(
            "get_event_detail",
            "Returns full detail for a specific event by event_id.",
            {"event_id": {"type": "integer", "description": "The event_id to retrieve"}},
            _get_event_detail,
        ),
        Tool(
            "get_known_issues",
            "Returns known hardware/firmware issues for the detected chip_gen.",
            {},
            _get_known_issues,
        ),
        Tool(
            "get_subsystem_events",
            "Returns all events belonging to a specific subsystem.",
            {"subsystem": {"type": "string", "enum": SUBSYSTEM_ENUM}},
            _get_subsystem_events,
        ),
        Tool(
            "get_provider_info",
            "Returns the detected SoC provider name, chip_gen, arch, kernel version.",
            {},
            lambda ctx: {
                "provider":   ctx.cascade.events[0].provider_name
                              if ctx.cascade.events else "generic",
                "chip_gen":   ctx.cascade.chip_gen,
                "arch":       ctx.cascade.arch,
                "kernel_ver": ctx.cascade.kernel_ver,
            },
        ),
        Tool(
            "get_ip_blocks",
            "Returns all unique IP blocks identified across all events.",
            {},
            lambda ctx: list(
                {e.ip_block for e in ctx.cascade.events if e.ip_block != "unknown"}
            ),
        ),
        Tool(
            "get_severity_summary",
            "Returns count of events by severity and overall severity level.",
            {},
            lambda ctx: {
                "overall":  ctx.cascade.severity,
                "critical": ctx.cascade.critical_count,
                "error":    ctx.cascade.error_count,
                "warning":  ctx.cascade.warning_count,
                "info":     ctx.cascade.info_count,
                "total":    ctx.cascade.event_count,
            },
        ),
        Tool(
            "get_call_trace",
            "Returns call trace frames from a specific event.",
            {"event_id": {"type": "integer"}},
            _get_call_trace,
        ),
    ]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools   = _build_tools()
        self._tool_map = {t.name: t for t in self._tools}

    def all_tools(self) -> list[Tool]:
        return self._tools

    def execute(self, tool_name: str, arguments: dict, ctx: AgentContext) -> dict:
        """Execute a tool by name. Returns error dict on unknown tool — never raises."""
        tool = self._tool_map.get(tool_name)
        if tool is None:
            return {"error": f"unknown tool: {tool_name}"}
        try:
            result = tool.fn(ctx, **arguments)
            if not isinstance(result, dict):
                result = {"result": result}
            return result
        except Exception as exc:
            return {"error": str(exc)}
