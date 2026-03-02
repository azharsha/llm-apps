"""
Tool schemas and dispatch for port_agent.

TOOL_SCHEMAS — passed to Claude API in the tools= parameter.
dispatch_tool(name, input) — returns JSON-encoded string result.
"""
import json
from pathlib import Path

from git import conflict as conflict_mod
from git import repo as repo_mod

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "list_commits_to_port",
        "description": (
            "Find commits in the upstream kernel tree (restricted to the specified "
            "directories) that are NOT yet present in the downstream kernel tree. "
            "Returns commits in oldest-first (topological) order, ready for "
            "cherry-picking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "upstream_path": {"type": "string", "description": "Absolute path to the upstream kernel repo"},
                "downstream_path": {"type": "string", "description": "Absolute path to the downstream kernel repo"},
                "upstream_branch": {"type": "string", "description": "Branch name in the upstream repo"},
                "downstream_branch": {"type": "string", "description": "Branch name in the downstream repo"},
                "dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of kernel subdirectories to restrict the search (e.g. ['drivers/gpu/drm'])",
                },
                "max_commits": {
                    "type": "integer",
                    "description": "Maximum number of commits to return",
                    "default": 50,
                },
                "since_tag": {
                    "type": "string",
                    "description": (
                        "Optional git tag or commit in the upstream repo to use as the "
                        "exclusive lower bound (e.g. 'v6.6-rc7'). Use this when the upstream "
                        "and downstream repos do not share git history (cross-repo porting). "
                        "Only commits AFTER this tag will be considered for porting."
                    ),
                },
            },
            "required": ["upstream_path", "downstream_path", "upstream_branch", "downstream_branch", "dirs"],
        },
    },
    {
        "name": "get_commit_details",
        "description": (
            "Get the full commit message, diff, and file list for a single commit. "
            "Call this before cherry-picking to understand what a commit does."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the repo containing the commit"},
                "commit_hash": {"type": "string", "description": "Full or short commit hash"},
            },
            "required": ["repo_path", "commit_hash"],
        },
    },
    {
        "name": "cherry_pick_commit",
        "description": (
            "Apply a single upstream commit to the current work branch. "
            "Uses git format-patch | git am --3way so no cross-repo fetch is needed. "
            "Returns success=true on clean apply, or "
            "success=false with conflicted_files list when conflicts occur."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "commit_hash": {"type": "string", "description": "Upstream commit hash to apply"},
                "upstream_path": {"type": "string", "description": "Absolute path to the upstream repo (required for cross-repo porting)"},
            },
            "required": ["repo_path", "commit_hash"],
        },
    },
    {
        "name": "get_conflict_details",
        "description": (
            "Read the conflict markers (<<<<<<< HEAD / ======= / >>>>>>>) for "
            "one or more conflicted files after a failed cherry-pick. Returns "
            "structured ours/theirs sections for analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "conflicted_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of conflicted file paths (relative to repo root)",
                },
            },
            "required": ["repo_path", "conflicted_files"],
        },
    },
    {
        "name": "apply_conflict_resolution",
        "description": (
            "Write a proposed conflict resolution to one file (no conflict markers) "
            "and stage it. Call ask_user_to_resolve_conflict BEFORE this tool to "
            "get user approval of the resolution content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "file_path": {"type": "string", "description": "Relative path to the conflicted file"},
                "resolved_content": {"type": "string", "description": "Full file content with conflicts resolved (no <<< markers)"},
            },
            "required": ["repo_path", "file_path", "resolved_content"],
        },
    },
    {
        "name": "ask_user_to_resolve_conflict",
        "description": (
            "PAUSE the agentic loop and show the conflict to the user. "
            "You MUST call get_conflict_details first, then propose your resolution, "
            "then call this tool. The user will see your proposed resolution and can "
            "accept it, modify it, provide their own, or skip/abort. "
            "This tool MUST be called for EVERY conflict — never auto-apply without user approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "conflict_file": {"type": "string", "description": "Relative path to the conflicted file"},
                "conflict_content": {"type": "string", "description": "The raw conflict markers content to display to the user"},
                "claude_suggestion": {"type": "string", "description": "Your proposed resolved file content (no conflict markers)"},
                "commit_subject": {"type": "string", "description": "Subject line of the commit being ported"},
            },
            "required": ["repo_path", "conflict_file", "conflict_content", "claude_suggestion", "commit_subject"],
        },
    },
    {
        "name": "run_checkpatch",
        "description": (
            "Run scripts/checkpatch.pl --strict on the last commit (HEAD). "
            "Call this after every successful cherry-pick or conflict resolution. "
            "Errors block the commit; warnings are informational."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "target": {
                    "type": "string",
                    "description": "Commit ref to check (default: HEAD)",
                    "default": "HEAD",
                },
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "run_build",
        "description": (
            "Run the user-supplied build command to validate compilation. "
            "Returns success, errors, and warnings. Only call this if build_cmd "
            "was provided by the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "build_cmd": {"type": "string", "description": "Shell command to run (e.g. 'make -j4 drivers/gpu/drm/')"},
            },
            "required": ["repo_path", "build_cmd"],
        },
    },
    {
        "name": "finalize_commit",
        "description": (
            "Run git cherry-pick --continue after all conflicted files have been "
            "resolved and staged. Then optionally amend the commit message to add "
            "the BACKPORT: prefix, Conflicts: section, and cherry-pick attribution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "amended_message": {
                    "type": "string",
                    "description": (
                        "Optional: full amended commit message with BACKPORT: prefix, "
                        "original body, Conflicts: section, and cherry-pick line. "
                        "If omitted, the existing message is kept."
                    ),
                },
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "create_commit",
        "description": (
            "Create a git commit for all currently staged files. "
            "Use this instead of finalize_commit when cherry_pick_commit returned "
            "mode='manual_apply_needed' and the patch was applied manually "
            "(not via git am). Stage all resolved files with apply_conflict_resolution "
            "first, then call this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "message": {"type": "string", "description": "Full commit message (BACKPORT: prefix, body, attribution)"},
            },
            "required": ["repo_path", "message"],
        },
    },
    {
        "name": "skip_commit",
        "description": (
            "Skip the current commit (run git cherry-pick --abort) and record the "
            "reason. Only use after user has explicitly chosen to skip."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to the downstream repo"},
                "commit_hash": {"type": "string", "description": "Upstream commit hash being skipped"},
                "reason": {"type": "string", "description": "Human-readable reason for skipping"},
            },
            "required": ["repo_path", "commit_hash", "reason"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Entry point for tool execution. Returns JSON-encoded string."""
    try:
        result = _execute_tool(tool_name, tool_input)
    except Exception as exc:
        result = {"error": f"Tool execution failed: {exc}"}
    return json.dumps(result, default=str)


def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    if tool_name == "list_commits_to_port":
        return repo_mod.get_commits_to_port(
            upstream_path=tool_input["upstream_path"],
            downstream_path=tool_input["downstream_path"],
            upstream_branch=tool_input["upstream_branch"],
            downstream_branch=tool_input["downstream_branch"],
            dirs=tool_input["dirs"],
            max_commits=tool_input.get("max_commits", 50),
            since_tag=tool_input.get("since_tag"),
        )

    elif tool_name == "get_commit_details":
        return repo_mod.get_commit_details(
            repo_path=tool_input["repo_path"],
            commit_hash=tool_input["commit_hash"],
        )

    elif tool_name == "cherry_pick_commit":
        return repo_mod.cherry_pick(
            downstream_path=tool_input["repo_path"],
            commit_hash=tool_input["commit_hash"],
            upstream_path=tool_input.get("upstream_path"),
        )

    elif tool_name == "get_conflict_details":
        conflicts = conflict_mod.parse_conflicts(
            repo_path=tool_input["repo_path"],
            conflicted_files=tool_input["conflicted_files"],
        )
        # Format each for Claude's consumption
        formatted = [conflict_mod.format_conflict_for_display(c) for c in conflicts]
        return {
            "conflicts": conflicts,
            "formatted_summary": "\n\n".join(formatted),
        }

    elif tool_name == "apply_conflict_resolution":
        result = conflict_mod.apply_resolution(
            repo_path=tool_input["repo_path"],
            file_path=tool_input["file_path"],
            resolved_content=tool_input["resolved_content"],
        )
        if result["success"]:
            # Stage the file immediately
            repo_mod.stage_file(
                repo_path=tool_input["repo_path"],
                file_path=tool_input["file_path"],
            )
        return result

    elif tool_name == "ask_user_to_resolve_conflict":
        # This is the interactive pause — blocks until user responds
        user_decision = conflict_mod.ask_user_to_resolve(
            repo_path=tool_input["repo_path"],
            conflict_file=tool_input["conflict_file"],
            conflict_content=tool_input["conflict_content"],
            claude_suggestion=tool_input["claude_suggestion"],
            commit_subject=tool_input.get("commit_subject", ""),
        )
        return user_decision

    elif tool_name == "run_checkpatch":
        return repo_mod.run_checkpatch(
            repo_path=tool_input["repo_path"],
            mode="commit",
            target=tool_input.get("target", "HEAD"),
        )

    elif tool_name == "run_build":
        return repo_mod.run_build(
            repo_path=tool_input["repo_path"],
            build_cmd=tool_input["build_cmd"],
        )

    elif tool_name == "finalize_commit":
        result = repo_mod.continue_cherry_pick(repo_path=tool_input["repo_path"])
        if result["success"] and tool_input.get("amended_message"):
            amend_result = repo_mod.amend_commit_message(
                repo_path=tool_input["repo_path"],
                message=tool_input["amended_message"],
            )
            result["amend"] = amend_result
        if result["success"]:
            result["new_commit_hash"] = repo_mod.get_last_commit_hash(tool_input["repo_path"])
        return result

    elif tool_name == "create_commit":
        result = repo_mod.create_commit(
            repo_path=tool_input["repo_path"],
            message=tool_input["message"],
        )
        if result.get("success"):
            # Remove all .rej files left behind by git apply --reject
            for rej in Path(tool_input["repo_path"]).rglob("*.rej"):
                rej.unlink(missing_ok=True)
        return result

    elif tool_name == "skip_commit":
        repo_mod.abort_cherry_pick(repo_path=tool_input["repo_path"])
        return {
            "skipped": True,
            "commit_hash": tool_input["commit_hash"],
            "reason": tool_input["reason"],
        }

    else:
        return {"error": f"Unknown tool: {tool_name}"}
