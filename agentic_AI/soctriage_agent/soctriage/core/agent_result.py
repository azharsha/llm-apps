"""
agent_result.py — Phase 6 v6.0.0

AgentResult and ToolCall dataclasses produced by the SoCTriageAgent loop.

Public symbols: ToolCall, AgentResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soctriage.core.cascade import CascadeResult

__all__ = ["ToolCall", "AgentResult"]


@dataclass
class ToolCall:
    tool_name:   str
    arguments:   dict
    response:    dict
    duration_ms: int
    call_index:  int   # 1-based within this agent run


@dataclass
class AgentResult:
    cascade:               "CascadeResult"
    root_cause_narrative:  str
    fix_suggestions:       list[str]
    known_issues_matched:  list[dict]
    confidence:            float        # 0.0–1.0
    subsystem_narrative:   str
    tool_trace:            list[ToolCall]
    llm_backend:           str          # "openai" | "ollama" | "none"
    llm_model:             str
    iterations:            int
    total_ms:              int
    offline_mode:          bool
    no_llm_mode:           bool

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict. cascade is embedded via cascade.to_dict()."""
        return {
            "root_cause_narrative": self.root_cause_narrative,
            "fix_suggestions":      self.fix_suggestions,
            "known_issues_matched": self.known_issues_matched,
            "confidence":           self.confidence,
            "subsystem_narrative":  self.subsystem_narrative,
            "tool_trace": [
                {
                    "tool_name":   tc.tool_name,
                    "arguments":   tc.arguments,
                    "response":    tc.response,
                    "duration_ms": tc.duration_ms,
                    "call_index":  tc.call_index,
                }
                for tc in self.tool_trace
            ],
            "llm_backend":  self.llm_backend,
            "llm_model":    self.llm_model,
            "iterations":   self.iterations,
            "total_ms":     self.total_ms,
            "offline_mode": self.offline_mode,
            "no_llm_mode":  self.no_llm_mode,
            "cascade":      self.cascade.to_dict(),
        }

    def to_markdown(self) -> str:
        """Render to Markdown for Phase 7 reporter consumption."""
        lines: list[str] = []
        lines.append("## SoCTriage Analysis")
        lines.append("")
        lines.append(f"**chip_gen:** `{self.cascade.chip_gen}`  ")
        lines.append(f"**arch:** `{self.cascade.arch}`  ")
        lines.append(f"**kernel:** `{self.cascade.kernel_ver or 'unknown'}`  ")
        lines.append(
            f"**backend:** `{self.llm_model}` "
            f"({self.iterations} iterations · {self.total_ms}ms)"
        )
        lines.append("")
        lines.append("### Root Cause")
        lines.append(self.root_cause_narrative)
        lines.append("")
        lines.append("### Cascade Diagram")
        lines.append("```")
        lines.append(self.cascade.ascii_diagram)
        lines.append("```")
        lines.append("")
        lines.append("### Fix Suggestions")
        for i, fix in enumerate(self.fix_suggestions, 1):
            lines.append(f"{i}. {fix}")
        lines.append("")
        if self.known_issues_matched:
            lines.append("### Known Issues Matched")
            for issue in self.known_issues_matched:
                lines.append(
                    f"- **{issue.get('issue_id', '?')}**: {issue.get('title', '?')}"
                )
                lines.append(f"  - Fixed in: `{issue.get('fixed_in', '?')}`")
                lines.append(f"  - Workaround: {issue.get('workaround', '?')}")
            lines.append("")
        lines.append("### Tool Call Trace")
        for tc in self.tool_trace:
            lines.append(
                f"{tc.call_index}. `{tc.tool_name}({tc.arguments})` → {tc.duration_ms}ms"
            )
        lines.append("")
        lines.append(f"**Agent confidence:** {self.confidence:.2f}")
        return "\n".join(lines)
