"""
Agentic loop for port_agent.

run_porting_session() drives the Claude tool-use loop that identifies,
cherry-picks, validates, and commits upstream kernel code into the
downstream tree.
"""
import json
from datetime import datetime
from pathlib import Path

import anthropic

import config
from agents.tools import TOOL_SCHEMAS, dispatch_tool

SYSTEM_PROMPT = """You are a senior Linux kernel engineer specializing in porting \
code between kernel trees (e.g. upstream Linux → ChromeOS kernel). \
You follow Linux kernel coding guidelines strictly (no style violations).

## Your workflow for EACH commit

1. Call `get_commit_details` to understand what the commit does.
2. Call `cherry_pick_commit` (always pass upstream_path) to apply it.
3a. If CLEAN apply (success=true):
    - Call `run_checkpatch` on HEAD.
    - If checkpatch has ERRORS (not warnings): fix them. Warnings are acceptable.
    - If `build_cmd` was provided, call `run_build`.
    - If build fails: analyze the error, explain the fix, create a follow-up commit.
3b. If standard CONFLICT (success=false, conflicted_files are path strings with <<<):
    - Call `get_conflict_details` to read all conflict markers (ours/theirs).
    - For EACH file: call `ask_user_to_resolve_conflict` with YOUR proposed resolution.
    - Apply user's decision with `apply_conflict_resolution` (stages the file).
    - Call `finalize_commit` with a properly formatted amended_message.
    - Call `run_checkpatch` and optionally `run_build`.
3c. If MANUAL APPLY NEEDED (success=false, mode="manual_apply_needed"):
    The file diverged too much for git am context matching. The .rej file shows \
the exact lines that could not be applied.
    - For EACH item in conflicted_files (contains file path + rej_content):
      a. Read the CURRENT downstream file content.
      b. Find the equivalent location using function names/comments in rej_content.
      c. Call `ask_user_to_resolve_conflict` with the full file showing YOUR manual \
application of the semantic change at the correct location.
      d. Apply with `apply_conflict_resolution` (writes + stages the file).
    - For any affected_files that applied cleanly (no .rej), they are already \
patched in the working tree — stage them by passing their current on-disk content \
to `apply_conflict_resolution`.
    - Once ALL files staged, call `create_commit` with the BACKPORT message.
    - Call `run_checkpatch` and optionally `run_build`.

## Commit message format for ported commits

```
BACKPORT: <original commit subject>

<original commit body verbatim>

Conflicts:
  <relative/path/to/file>: <one-line description of how conflict was resolved>

(cherry picked from commit <upstream_hash> in linux/main)
```

Always use the "BACKPORT:" prefix. If there were no conflicts, omit the \
"Conflicts:" section. The cherry-pick line is added automatically by \
`git cherry-pick -x`, but you should include it in amended_message for clarity.

## Linux kernel coding guidelines

- Tabs for indentation (8 spaces wide), not spaces.
- Lines ≤ 80 chars where possible (100 is acceptable for long expressions).
- No trailing whitespace.
- Function names: lowercase_with_underscores.
- No unnecessary typedefs.
- Comments explain WHY, not WHAT.
- `checkpatch.pl --strict` must pass with 0 errors before finalizing.

## Important rules

- NEVER skip a commit without calling `skip_commit` tool (and only after the \
user has chosen to skip in `ask_user_to_resolve_conflict`).
- Process commits in the order given by `list_commits_to_port` (oldest first).
- After every finalized commit, summarize what was ported and any issues found.
- If the user's decision from `ask_user_to_resolve_conflict` is \
action="skip_commit", call `skip_commit` immediately.
- If action="abort", stop processing and return your final summary.
- Be concise in your tool calls; do not repeat large diffs back unnecessarily.
"""


def run_porting_session(
    upstream_path: str,
    downstream_path: str,
    upstream_branch: str,
    downstream_branch: str,
    dirs: list[str],
    work_branch: str,
    build_cmd: str | None,
    max_commits: int,
    since_tag: str | None,
    dry_run: bool,
    progress_callback=None,
) -> dict:
    """
    Main agentic loop. Returns a result dict with porting summary.
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build the initial user message
    build_info = f'build_cmd="{build_cmd}"' if build_cmd else "no build command (checkpatch only)"
    dirs_str = ", ".join(dirs)
    since_info = f'since_tag="{since_tag}"' if since_tag else "since_tag=None (auto-detect merge-base)"

    initial_message = (
        f"Port upstream kernel commits to the downstream tree.\n\n"
        f"Configuration:\n"
        f"- upstream_path: {upstream_path}\n"
        f"- downstream_path: {downstream_path}\n"
        f"- upstream_branch: {upstream_branch}\n"
        f"- downstream_branch: {downstream_branch}\n"
        f"- work_branch: {work_branch} (already created and checked out)\n"
        f"- directories to port: {dirs_str}\n"
        f"- max_commits: {max_commits}\n"
        f"- {since_info}\n"
        f"- {build_info}\n"
        f"- dry_run: {dry_run}\n\n"
        f"{'DRY RUN: Identify commits to port but DO NOT apply them. List what would be ported.' if dry_run else f'Begin: call list_commits_to_port (pass since_tag if provided), then for each commit call cherry_pick_commit with upstream_path={upstream_path} so patches are applied without a cross-repo fetch.'}"
    )

    messages = [{"role": "user", "content": initial_message}]
    tools_used: list[str] = []
    ported_commits: list[dict] = []
    skipped_commits: list[dict] = []
    iterations = 0

    for iteration in range(config.MAX_AGENT_ITERATIONS):
        iterations = iteration + 1

        if progress_callback:
            progress_callback(f"Agent iteration {iterations}...")

        response = client.messages.create(
            model=config.MODEL,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Collect tool_use blocks
        tool_use_blocks = []
        for block in response.content:
            if block.type == "tool_use":
                tool_use_blocks.append(block)

        # Append assistant message
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # Execute all tool calls
        tool_results = []
        for tb in tool_use_blocks:
            tools_used.append(tb.name)
            if progress_callback:
                progress_callback(f"Tool: {tb.name}")

            raw_result = dispatch_tool(tb.name, tb.input)
            try:
                result_data = json.loads(raw_result)
            except json.JSONDecodeError:
                result_data = {"error": f"Malformed JSON from tool {tb.name}"}

            # Track ported / skipped commits from tool results
            if tb.name == "finalize_commit" and result_data.get("success"):
                ported_commits.append({
                    "new_hash": result_data.get("new_commit_hash", ""),
                    "tool_input": tb.input,
                })
            elif tb.name == "create_commit" and result_data.get("success"):
                # Manual-apply path: create_commit is used instead of finalize_commit
                ported_commits.append({
                    "new_hash": result_data.get("commit_hash", ""),
                    "tool_input": tb.input,
                })
            elif tb.name == "skip_commit" and result_data.get("skipped"):
                skipped_commits.append({
                    "hash": result_data.get("commit_hash", ""),
                    "reason": result_data.get("reason", ""),
                })

            # Check for user abort signal
            if tb.name == "ask_user_to_resolve_conflict":
                if result_data.get("action") == "abort":
                    # Signal Claude to stop by injecting an abort note
                    raw_result = json.dumps({
                        **result_data,
                        "_note": "User aborted the session. Stop processing and summarize.",
                    })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": raw_result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Extract final text summary from the last assistant message
    final_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            for block in (msg.get("content") or []):
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            if final_text:
                break

    return {
        "summary": final_text,
        "ported_commits": ported_commits,
        "skipped_commits": skipped_commits,
        "tools_used": tools_used,
        "iterations": iterations,
        "upstream_path": upstream_path,
        "downstream_path": downstream_path,
        "work_branch": work_branch,
        "dirs": dirs,
        "build_cmd": build_cmd,
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
    }
