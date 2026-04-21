"""
agent.py — Phase 6 v6.0.0

SoCTriageAgent: autonomous tool-calling agent loop that wraps a CascadeResult
and produces a structured AgentResult with root-cause narrative, fix suggestions,
known-issues matching, and a full tool call trace.

Public symbols: SoCTriageAgent, run_agent, _fallback_agent_result, _parse_agent_result
"""

from __future__ import annotations

import json
import time
import logging
from typing import Any

from soctriage.core.cascade       import CascadeResult
from soctriage.core.agent_result  import AgentResult, ToolCall
from soctriage.core.tool_registry import AgentContext, ToolRegistry
from soctriage.core.prompts       import _build_system_message, USER_PROMPT
from soctriage.core.llm_client    import LLMClient, LLMResponse

__all__ = ["SoCTriageAgent", "run_agent", "_fallback_agent_result", "_parse_agent_result"]

logger = logging.getLogger(__name__)


# ── Deterministic fallback ────────────────────────────────────────────────────


def _fallback_agent_result(cascade: CascadeResult, error: str = "") -> AgentResult:
    """
    Called when LLM fails, times out, or is unavailable.
    Produces a valid AgentResult from Phase 4 data alone — no LLM required.
    Sets no_llm_mode=True and iterations=0.
    """
    root = cascade.to_dict().get("root_cause") or {}
    return AgentResult(
        cascade              = cascade,
        root_cause_narrative = (
            f"Root cause identified as {root.get('event_type', 'unknown')} "
            f"in subsystem {root.get('subsystem', 'unknown')} "
            f"(confidence {root.get('confidence', 0.0):.2f}). "
            f"LLM narrative unavailable: {error or 'offline mode'}."
        ),
        fix_suggestions      = ["See known issues database for this chip_gen."],
        known_issues_matched = [],
        confidence           = cascade.root_cause_conf * 0.7,
        subsystem_narrative  = "",
        tool_trace           = [],
        llm_backend          = "none",
        llm_model            = "none",
        iterations           = 0,
        total_ms             = 0,
        offline_mode         = False,
        no_llm_mode          = True,
    )


# ── Response parser ───────────────────────────────────────────────────────────


def _parse_agent_result(
    final_text: str | None,
    cascade:    CascadeResult,
    tool_trace: list[ToolCall],
    iterations: int,
    total_ms:   int,
    llm_backend: str = "openai",
    llm_model:   str = "gpt-4o",
) -> AgentResult:
    """
    Parse the LLM's final response (JSON or free-text) into an AgentResult.

    Expected JSON keys: root_cause_narrative, fix_suggestions, confidence,
    subsystem_narrative, known_issues_matched.
    Falls back to treating the entire text as root_cause_narrative.
    """
    if not final_text:
        fb = _fallback_agent_result(cascade, error="no final text from LLM")
        # Preserve the actual iteration count even in fallback path
        fb.iterations = iterations
        fb.total_ms   = total_ms
        fb.llm_backend = llm_backend
        fb.llm_model   = llm_model
        return fb

    root_cause_narrative = final_text
    fix_suggestions:      list[str]  = []
    known_issues_matched: list[dict] = []
    confidence            = cascade.root_cause_conf
    subsystem_narrative   = ""

    # Try to parse JSON from the response
    try:
        # Handle markdown code fences
        text = final_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # strip opening fence
            lines = lines[1:]
            # strip closing fence
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        data = json.loads(text)
        root_cause_narrative = data.get("root_cause_narrative", final_text)
        fix_suggestions      = data.get("fix_suggestions", [])
        known_issues_matched = data.get("known_issues_matched", [])
        confidence           = float(data.get("confidence", cascade.root_cause_conf))
        subsystem_narrative  = data.get("subsystem_narrative", "")
    except (json.JSONDecodeError, ValueError, TypeError):
        # Free-text response — keep the full text as narrative
        pass

    # Clamp confidence to [0.0, 1.0]
    confidence = max(0.0, min(1.0, confidence))

    return AgentResult(
        cascade              = cascade,
        root_cause_narrative = root_cause_narrative,
        fix_suggestions      = fix_suggestions,
        known_issues_matched = known_issues_matched,
        confidence           = confidence,
        subsystem_narrative  = subsystem_narrative,
        tool_trace           = tool_trace,
        llm_backend          = llm_backend,
        llm_model            = llm_model,
        iterations           = iterations,
        total_ms             = total_ms,
        offline_mode         = False,
        no_llm_mode          = False,
    )


# ── Agent class ───────────────────────────────────────────────────────────────


class SoCTriageAgent:
    """
    Autonomous tool-calling agent loop.

    Wraps a CascadeResult, calls tools via the LLMClient, and returns an AgentResult.
    Never raises — all exceptions are caught and return _fallback_agent_result.
    """

    MAX_ITERATIONS = 8

    def __init__(
        self,
        llm_client:    LLMClient,
        tool_registry: ToolRegistry,
        provider:      Any = None,
    ) -> None:
        self._llm      = llm_client
        self._tools    = tool_registry
        self._provider = provider

    def run(self, cascade: CascadeResult) -> AgentResult:
        """
        Main agent loop. Returns AgentResult — never raises.

        Loop protocol:
        1. Build [system_msg, user_msg]
        2. resp = llm.chat(messages, registry.all_tools())
        3. stop_reason == "tool_calls" → execute each tool, append assistant + tool
           messages, continue
        4. stop_reason == "stop" + content → _parse_agent_result(), break
        5. Other stop reason (length/error) → break with partial result
        6. iterations >= MAX_ITERATIONS → break
        """
        start_ns = time.perf_counter_ns()

        ctx        = AgentContext(cascade=cascade, provider=self._provider)
        system_msg = _build_system_message(cascade)
        user_msg   = {"role": "user", "content": USER_PROMPT}
        messages: list[dict] = [system_msg, user_msg]

        tool_trace: list[ToolCall] = []
        iterations  = 0
        final_text: str | None = None

        # Detect backend name for result metadata
        backend_name = type(self._llm).__name__.lower().replace("client", "")
        model_name   = getattr(self._llm, "_model", "unknown")

        try:
            while iterations < self.MAX_ITERATIONS:
                iterations += 1
                resp: LLMResponse = self._llm.chat(messages, self._tools.all_tools())

                if resp.stop_reason == "tool_calls" and resp.tool_calls:
                    results: list[dict] = []
                    for tc_req in resp.tool_calls:
                        t0 = time.perf_counter_ns()
                        result = self._tools.execute(tc_req.tool_name, tc_req.arguments, ctx)
                        t1 = time.perf_counter_ns()
                        tool_trace.append(ToolCall(
                            tool_name   = tc_req.tool_name,
                            arguments   = tc_req.arguments,
                            response    = result,
                            duration_ms = (t1 - t0) // 1_000_000,
                            call_index  = len(tool_trace) + 1,
                        ))
                        results.append(result)

                    # Append assistant turn with tool_calls
                    messages.append({
                        "role":       "assistant",
                        "content":    None,
                        "tool_calls": [
                            {
                                "id":       tc.id,
                                "type":     "function",
                                "function": {
                                    "name":      tc.tool_name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in resp.tool_calls
                        ],
                    })
                    # Append each tool result separately
                    for tc_req, result in zip(resp.tool_calls, results):
                        messages.append({
                            "role":         "tool",
                            "tool_call_id": tc_req.id,
                            "content":      json.dumps(result),
                        })

                elif resp.stop_reason == "stop" and resp.content:
                    final_text = resp.content
                    break

                else:
                    # length / error / empty tool_calls — break with what we have
                    if resp.content:
                        final_text = resp.content
                    break

        except Exception as exc:
            logger.warning("SoCTriageAgent: LLM error — %s", exc)
            return _fallback_agent_result(cascade, error=str(exc))

        total_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
        return _parse_agent_result(
            final_text,
            cascade,
            tool_trace,
            iterations,
            total_ms,
            llm_backend = backend_name,
            llm_model   = model_name,
        )


# ── Public entry point ────────────────────────────────────────────────────────


def run_agent(
    cascade:     CascadeResult,
    provider:    Any  = None,
    *,
    backend:     str  = "openai",
    model:       str  = "gpt-4o",
    ollama_host: str  = "http://localhost:11434",
    no_llm:      bool = False,
) -> AgentResult:
    """
    Top-level entry point called by Phase 7 CLI.

    Instantiates the correct LLMClient, builds the agent, runs the loop.

    When no_llm=True, returns _fallback_agent_result immediately without
    importing openai or httpx.
    """
    if no_llm:
        return _fallback_agent_result(cascade)

    if backend == "ollama":
        from soctriage.core.llm_client import OllamaClient
        client: LLMClient = OllamaClient(model=model, host=ollama_host)
    else:
        from soctriage.core.llm_client import OpenAIClient
        client = OpenAIClient(model=model)

    registry = ToolRegistry()
    agent    = SoCTriageAgent(client, registry, provider=provider)
    return agent.run(cascade)
