"""Generic LLM domain agent agentic loop.

[PRD §4.1] Each domain agent follows this pattern:
  1. Receive system prompt + user prompt (domain + board context)
  2. LLM calls tools (exec_command, read_file, path_exists, glob, emit_finding)
  3. Tools dispatch to ProbeRunner on the target board
  4. LLM calls complete_domain → loop exits
  5. DomainResult assembled from findings + completion data

[N-PG-04] tenacity retry on Claude API 429/503/RateLimitError.
[SG-06] agent_timeout_seconds wall-clock cap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import anthropic
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

from poagent.agents.tools import DOMAIN_AGENT_TOOLS, dispatch_tool
from poagent.agents.prompts import DOMAIN_SYSTEM_PROMPTS, build_domain_user_prompt
from poagent.codes import AGENT_API_RETRY, AGENT_TIMEOUT

log = structlog.get_logger(__name__)

DomainStatus = Literal[
    "pass", "fail", "warning", "conditional", "skip",
    "aborted", "skip_debugfs", "enum_fail", "dependent_fail"
]


@dataclass
class Finding:
    """Single structured finding from an agent."""
    severity: str
    code: str
    message: str
    evidence: dict = field(default_factory=dict)
    recommended_action: str = ""


@dataclass
class DomainResult:
    """Result of a single domain agent run.

    [SG-06] timed_out_probes replaces timed_out: bool.
    [FINAL-S4] gate4_method5_only tags all results when Gate4 used Method 5.
    """
    domain: str
    status: str  # DomainStatus
    summary: str
    findings: list[Finding] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    confidence: float = 0.0
    recommended_actions: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
    iterations: int = 0
    tools_called: list[str] = field(default_factory=list)
    timed_out_probes: list[str] = field(default_factory=list)
    debugfs_probes_skipped: int = 0
    gate4_method5_only: bool = False
    confidence_tags: list[str] = field(default_factory=list)
    cascade_root: Optional[str] = None
    failed_clocks: list[str] = field(default_factory=list)

    def get_failed_clocks(self) -> list[str]:
        """Return failed clocks list (for cascade resolver [CG-04])."""
        if self.failed_clocks:
            return self.failed_clocks
        return self.raw_data.get("failed_clocks", [])

    def to_summary_dict(self) -> dict:
        """Compact summary for Triage Agent input (≤ 500 tokens target)."""
        return {
            "domain": self.domain,
            "status": self.status,
            "summary": self.summary[:1000],
            "top_findings": [
                {"severity": f.severity, "code": f.code, "message": f.message[:200]}
                for f in self.findings[:5]
            ],
            "root_cause_hypothesis": self.root_cause_hypothesis[:500],
            "confidence": self.confidence,
            "timed_out_probes": self.timed_out_probes,
            "confidence_tags": self.confidence_tags,
        }


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, anthropic.RateLimitError) or (
        isinstance(exc, anthropic.APIStatusError) and exc.status_code in (503, 529)
    )


@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_claude_with_tools(
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    tools: list[dict],
) -> Any:
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=tools,  # type: ignore[arg-type]
        tool_choice={"type": "auto"},
    )


def run_domain_agent(
    domain: str,
    runner: object,
    board_profile: object,
    boot_context: dict,
    config: object,
    api_key: str,
    enum_failures: Optional[list[str]] = None,
    debugfs_available: bool = True,
    gate4_method5_only: bool = False,
) -> DomainResult:
    """Run one domain LLM agent with tool use loop.

    This is the generic agentic loop used by all 10 domain agents.
    Returns DomainResult.
    """
    if enum_failures is None:
        enum_failures = []

    agent_timeout_s: int = getattr(config, "agent_timeout_seconds", 120)
    max_iterations: int = getattr(config, "max_agent_iterations", 10)
    model: str = getattr(config, "model", "claude-sonnet-4-6")
    pause_event = getattr(config, "_pause_event", None)
    abort_event = getattr(config, "_abort_event", None)

    system_prompt = DOMAIN_SYSTEM_PROMPTS.get(domain, "")
    if not system_prompt:
        log.warning("domain_no_system_prompt", domain=domain)

    user_prompt = build_domain_user_prompt(
        domain=domain,
        board_profile=board_profile,
        boot_context=boot_context,
        enum_failures=enum_failures,
        debugfs_available=debugfs_available,
        gate4_method5_only=gate4_method5_only,
        agent_timeout_s=agent_timeout_s,
        max_iterations=max_iterations,
    )

    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    findings: list[Finding] = []
    domain_complete: dict = {}
    tools_called: list[str] = []
    timed_out_probes: list[str] = []
    iteration = 0
    start_time = time.time()

    log.info("domain_agent_start", domain=domain, model=model, timeout_s=agent_timeout_s)

    while iteration < max_iterations:
        # Check abort event
        if abort_event and abort_event.is_set():
            log.warning("domain_agent_aborted_thermal", domain=domain)
            return DomainResult(
                domain=domain,
                status="aborted",
                summary=f"Domain {domain} aborted by thermal/abort event.",
                findings=findings,
                iterations=iteration,
                tools_called=tools_called,
                timed_out_probes=timed_out_probes,
                gate4_method5_only=gate4_method5_only,
            )

        # Check wall-clock timeout
        elapsed = time.time() - start_time
        if elapsed >= agent_timeout_s:
            log.warning(AGENT_TIMEOUT, domain=domain, elapsed_s=round(elapsed, 1))
            return DomainResult(
                domain=domain,
                status="aborted",
                summary=(
                    f"Domain {domain} agent timed out after {elapsed:.0f}s "
                    f"(limit: {agent_timeout_s}s). "
                    f"Completed {iteration} iterations."
                ),
                findings=findings,
                root_cause_hypothesis="Agent timed out before completing analysis.",
                iterations=iteration,
                tools_called=tools_called,
                timed_out_probes=timed_out_probes,
                gate4_method5_only=gate4_method5_only,
            )

        # Pause event check (thermal monitor)
        if pause_event and pause_event.is_set():
            log.info("domain_agent_paused_thermal", domain=domain)
            pause_event.wait()
            log.info("domain_agent_resumed", domain=domain)

        # LLM API call
        try:
            response = _call_claude_with_tools(
                client=client,
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=DOMAIN_AGENT_TOOLS,
            )
        except RetryError as exc:
            log.error(AGENT_API_RETRY, domain=domain, error=str(exc))
            return DomainResult(
                domain=domain,
                status="aborted",
                summary=f"Domain {domain} aborted: API error after retries. {exc}",
                findings=findings,
                iterations=iteration,
                tools_called=tools_called,
                gate4_method5_only=gate4_method5_only,
            )
        except Exception as exc:
            log.error("domain_agent_api_error", domain=domain, error=str(exc))
            return DomainResult(
                domain=domain,
                status="aborted",
                summary=f"Domain {domain} aborted: {exc}",
                findings=findings,
                iterations=iteration,
                tools_called=tools_called,
                gate4_method5_only=gate4_method5_only,
            )

        iteration += 1

        # Collect assistant message
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Process tool calls
        if response.stop_reason == "tool_use":
            tool_results = []
            should_stop = False

            for block in assistant_content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input or {}
                tools_called.append(tool_name)

                log.debug("domain_tool_call",
                          domain=domain, tool=tool_name,
                          iteration=iteration)

                result_str, stop = dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    runner=runner,
                    findings=findings,
                    domain_complete=domain_complete,
                )

                # Convert emit_finding to Finding objects
                if tool_name == "emit_finding" and findings:
                    last = findings[-1]
                    if isinstance(last, dict):
                        findings[-1] = Finding(
                            severity=last.get("severity", "INFO"),
                            code=last.get("code", "UNKNOWN"),
                            message=last.get("message", ""),
                            evidence=last.get("evidence", {}),
                            recommended_action=last.get("recommended_action", ""),
                        )

                # Track timed-out probes
                import json as _json
                try:
                    result_dict = _json.loads(result_str)
                    if result_dict.get("timed_out"):
                        timed_out_probe = f"{tool_name}:{tool_input.get('command', '')[:50]}"
                        timed_out_probes.append(timed_out_probe)
                except (ValueError, KeyError):
                    pass

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

                if stop:
                    should_stop = True

            messages.append({"role": "user", "content": tool_results})

            if should_stop:
                break

        elif response.stop_reason == "end_turn":
            # LLM finished without calling complete_domain — extract text
            text = ""
            for block in assistant_content:
                if hasattr(block, "text"):
                    text += block.text
            log.warning("domain_agent_no_complete_tool", domain=domain, text=text[:200])
            domain_complete = {
                "status": "warning",
                "summary": text[:1000] or f"Domain {domain} completed without structured result.",
                "root_cause_hypothesis": "",
                "confidence": 0.3,
                "recommended_actions": [],
            }
            break

    # Normalize findings list
    normalized_findings: list[Finding] = []
    for f in findings:
        if isinstance(f, Finding):
            normalized_findings.append(f)
        elif isinstance(f, dict):
            normalized_findings.append(Finding(
                severity=f.get("severity", "INFO"),
                code=f.get("code", "UNKNOWN"),
                message=f.get("message", ""),
                evidence=f.get("evidence", {}),
                recommended_action=f.get("recommended_action", ""),
            ))

    result = DomainResult(
        domain=domain,
        status=domain_complete.get("status", "aborted"),
        summary=domain_complete.get("summary", ""),
        findings=normalized_findings,
        root_cause_hypothesis=domain_complete.get("root_cause_hypothesis", ""),
        confidence=float(domain_complete.get("confidence", 0.0)),
        recommended_actions=domain_complete.get("recommended_actions", []),
        raw_data={"failed_clocks": domain_complete.get("failed_clocks", [])},
        iterations=iteration,
        tools_called=tools_called,
        timed_out_probes=timed_out_probes,
        gate4_method5_only=gate4_method5_only,
        failed_clocks=domain_complete.get("failed_clocks", []),
    )

    log.info("domain_agent_complete",
             domain=domain,
             status=result.status,
             iterations=iteration,
             findings=len(normalized_findings),
             timed_out=len(timed_out_probes))

    return result
