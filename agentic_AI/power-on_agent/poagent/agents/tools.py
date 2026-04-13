"""Tool definitions for Claude LLM domain agents.

Each tool maps to a ProbeRunner method + structured output parsing.
Tools are called by the agentic loop in specialist.py.

Tool schema follows the Anthropic tool use format:
  name, description, input_schema (JSON Schema)
"""

from __future__ import annotations

from typing import Any

# ── Tool definitions (Anthropic API format) ───────────────────────────────────

EXEC_COMMAND_TOOL = {
    "name": "exec_command",
    "description": (
        "Execute a shell command on the target board via SSH/serial and return stdout, "
        "stderr, and returncode. Use for probing sysfs, procfs, and board diagnostics. "
        "Commands must be read-only unless explicitly authorized. "
        "Timeout enforced per PRD §3.8."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute on the target board.",
            },
            "timeout": {
                "type": "number",
                "description": "Command timeout in seconds (default 30, max 120).",
                "default": 30,
            },
            "min_output_len": {
                "type": "integer",
                "description": (
                    "Minimum expected output length in chars. If output is shorter, "
                    "a retry is attempted once (serial truncation detection [SG-05])."
                ),
                "default": 0,
            },
        },
        "required": ["command"],
    },
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read a file from the target board. Returns file contents as string. "
        "Equivalent to exec_command('cat <path>') but more readable in tool calls."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to read on the target board.",
            }
        },
        "required": ["path"],
    },
}

PATH_EXISTS_TOOL = {
    "name": "path_exists",
    "description": "Check if a path exists on the target board. Returns true/false.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to check on the target board.",
            }
        },
        "required": ["path"],
    },
}

GLOB_TOOL = {
    "name": "glob",
    "description": (
        "Expand a glob pattern on the target board. "
        "Returns a list of matching paths. "
        "Example: /sys/class/thermal/thermal_zone* returns all thermal zones."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Shell glob pattern to expand on the target board.",
            }
        },
        "required": ["pattern"],
    },
}

EMIT_FINDING_TOOL = {
    "name": "emit_finding",
    "description": (
        "Record a structured finding from the probe results. "
        "Call this for each significant finding (pass, fail, or warning). "
        "The orchestrator collects all findings into the DomainResult."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["PASS", "FAIL", "CONDITIONAL", "WARNING", "INFO", "SKIP"],
                "description": "Finding severity level.",
            },
            "code": {
                "type": "string",
                "description": "Error/warning code from poagent.codes (e.g. RAIL_SANITY_FAIL).",
            },
            "message": {
                "type": "string",
                "description": "Human-readable description of the finding.",
            },
            "evidence": {
                "type": "object",
                "description": "Key-value pairs of supporting evidence (paths, values, raw output).",
            },
            "recommended_action": {
                "type": "string",
                "description": "Suggested remediation step for this finding.",
            },
        },
        "required": ["severity", "code", "message"],
    },
}

COMPLETE_DOMAIN_TOOL = {
    "name": "complete_domain",
    "description": (
        "Signal that the domain agent has finished probing. "
        "Provide a summary, root cause hypothesis, and overall status. "
        "This MUST be the last tool called — the agentic loop exits after this."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pass", "fail", "warning", "conditional", "skip", "aborted"],
                "description": "Overall domain status.",
            },
            "summary": {
                "type": "string",
                "description": "One-paragraph summary of domain findings (≤ 500 tokens).",
            },
            "root_cause_hypothesis": {
                "type": "string",
                "description": (
                    "Root cause hypothesis for any failures. "
                    "Empty string if status is pass."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in root cause hypothesis (0.0–1.0).",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of recommended remediation actions.",
            },
            "failed_clocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "For Power & Clocking domain only: list of clock names that "
                    "failed to lock or enable (used by cascade resolver [CG-04])."
                ),
            },
        },
        "required": ["status", "summary", "root_cause_hypothesis", "confidence"],
    },
}

# All tools available to domain agents
DOMAIN_AGENT_TOOLS = [
    EXEC_COMMAND_TOOL,
    READ_FILE_TOOL,
    PATH_EXISTS_TOOL,
    GLOB_TOOL,
    EMIT_FINDING_TOOL,
    COMPLETE_DOMAIN_TOOL,
]

# Tool names for quick lookup
TOOL_NAMES = {t["name"] for t in DOMAIN_AGENT_TOOLS}


def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    runner: object,
    findings: list,
    domain_complete: dict,
) -> tuple[str, bool]:
    """Dispatch a tool call from the LLM to the appropriate ProbeRunner method.

    Returns (result_str, should_stop).
    should_stop=True when complete_domain is called.
    """
    import json

    if tool_name == "exec_command":
        cmd = tool_input["command"]
        timeout = float(tool_input.get("timeout", 30))
        min_len = int(tool_input.get("min_output_len", 0))
        result = runner.exec(cmd, timeout=timeout, min_output_len=min_len)  # type: ignore[union-attr]
        out = {
            "stdout": result.stdout[:4096],  # truncate very long outputs
            "stderr": result.stderr[:512],
            "returncode": result.returncode,
            "timed_out": result.timed_out,
        }
        if result.warnings:
            out["warnings"] = result.warnings
        return json.dumps(out), False

    elif tool_name == "read_file":
        path = tool_input["path"]
        content = runner.read_file(path)  # type: ignore[union-attr]
        return json.dumps({"content": content[:4096]}), False

    elif tool_name == "path_exists":
        path = tool_input["path"]
        exists = runner.path_exists(path)  # type: ignore[union-attr]
        return json.dumps({"exists": exists, "path": path}), False

    elif tool_name == "glob":
        pattern = tool_input["pattern"]
        paths = runner.glob(pattern)  # type: ignore[union-attr]
        return json.dumps({"paths": paths}), False

    elif tool_name == "emit_finding":
        findings.append(dict(tool_input))
        return json.dumps({"recorded": True}), False

    elif tool_name == "complete_domain":
        domain_complete.update(tool_input)
        return json.dumps({"complete": True}), True

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"}), False
