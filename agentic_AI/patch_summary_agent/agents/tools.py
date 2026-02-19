"""
Tool schemas and dispatch for the patch-summary Claude agent.

Tools exposed to Claude:
  - fetch_recent_patches   → list recent LKML patches (metadata)
  - get_patch_details      → full diff + subsystem + ABI analysis for one patch
  - get_series_patches     → all patches in a named series
"""
import json

from fetcher.patchwork import fetch_patches, fetch_patch_by_id, fetch_series_by_id
from fetcher.parser import (
    extract_files_changed,
    detect_subsystem,
    check_abi_breaking,
    check_memory_leaks,
    parse_diff_stats,
    parse_patch_subject,
)
from config import MAX_DIFF_CHARS


# ---------------------------------------------------------------------------
# Schema definitions (Anthropic tool_use format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "fetch_recent_patches",
        "description": (
            "Fetch a list of recent Linux kernel patches from patchwork.kernel.org, "
            "ordered newest-first. Returns patch metadata (id, subject, date, submitter, "
            "series IDs) — use get_patch_details to retrieve the actual diff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of patches to fetch (default 15, max 50).",
                    "default": 15,
                },
                "days_back": {
                    "type": "number",
                    "description": "How many days back to look (default 1, can be fractional e.g. 0.5).",
                    "default": 1,
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Patchwork project link_name or numeric ID to filter by "
                        "(optional). Examples: 'linux-usb', 'netdev', 'dri-devel', "
                        "'linux-scsi', 'linux-hwmon', 'linux-pm', 'linux-crypto'."
                    ),
                },
                "subsystem_filter": {
                    "type": "string",
                    "description": (
                        "Optional keyword to restrict results within a project. "
                        "Matched case-insensitively against patch subjects. "
                        "E.g. 'ehci', 'iwlwifi', 'btrfs', 'amdgpu'."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_patch_details",
        "description": (
            "Get full details for a specific patch by its Patchwork ID, including: "
            "diff content, files changed, automatically detected kernel subsystem, "
            "diff statistics (additions/deletions), and ABI/breaking-change flags. "
            "Call this after fetch_recent_patches to analyse individual patches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {
                    "type": "integer",
                    "description": "Numeric Patchwork patch ID (from fetch_recent_patches results).",
                },
            },
            "required": ["patch_id"],
        },
    },
    {
        "name": "get_series_patches",
        "description": (
            "Get all patches that belong to a series (cover letter + numbered patches). "
            "Returns the series name, submitter, total patch count, cover-letter excerpt, "
            "and list of individual patch IDs/subjects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "integer",
                    "description": "Numeric Patchwork series ID (from fetch_recent_patches results).",
                },
            },
            "required": ["series_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return its result as a JSON string."""
    try:
        result = _execute_tool(tool_name, tool_input)
    except Exception as exc:
        result = {"error": f"Tool execution failed: {exc}", "tool": tool_name}
    return json.dumps(result, default=str)


def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    # ------------------------------------------------------------------
    if tool_name == "fetch_recent_patches":
        limit = min(int(tool_input.get("limit", 15)), 50)
        days_back = float(tool_input.get("days_back", 1))
        project = tool_input.get("project")
        subsystem_filter = (tool_input.get("subsystem_filter") or "").strip().lower()

        raw_patches = fetch_patches(limit=limit, days_back=days_back, project=project)

        # Warn early if the project name returned nothing — likely a typo
        if project and not raw_patches:
            return {
                "error": (
                    f"No patches found for project='{project}'. "
                    "The project name must match a Patchwork link_name exactly. "
                    "Common DRM/GPU names: 'dri-devel', 'intel-gfx', 'amd-gfx'. "
                    "Run  python main.py --list-projects  to see all valid names."
                ),
                "hint": "Use --list-projects to discover the correct link_name.",
            }

        # Optional keyword filter on subject (case-insensitive)
        if subsystem_filter:
            raw_patches = [
                p for p in raw_patches
                if subsystem_filter in (p.get("name") or "").lower()
            ]

        results = []
        for p in raw_patches:
            series_ids = [s["id"] for s in p.get("series", [])]
            parsed = parse_patch_subject(p.get("name", ""))
            results.append({
                "id": p["id"],
                "subject": p.get("name", ""),
                "description": parsed["description"],
                "date": p.get("date", ""),
                "submitter": p.get("submitter", {}).get("name", "Unknown"),
                "submitter_email": p.get("submitter", {}).get("email", ""),
                "project": p.get("project", {}).get("name", ""),
                "state": p.get("state", ""),
                "series_ids": series_ids,
                "patch_num": parsed["patch_num"],
                "total_patches": parsed["total_patches"],
                "version": parsed["version"],
                "web_url": p.get("web_url", ""),
            })

        return {"patches": results, "count": len(results)}

    # ------------------------------------------------------------------
    elif tool_name == "get_patch_details":
        patch_id = int(tool_input["patch_id"])
        p = fetch_patch_by_id(patch_id)

        diff = p.get("diff") or ""
        content = p.get("content") or ""
        subject = p.get("name", "")

        files_changed = extract_files_changed(diff)
        subsystem = detect_subsystem(files_changed, subject)
        abi_flags = check_abi_breaking(diff, subject, content)
        memory_leak_flags = check_memory_leaks(diff, subject, content)
        stats = parse_diff_stats(diff)

        # Truncate large diffs — model doesn't need the full text
        diff_out = diff[:MAX_DIFF_CHARS]
        if len(diff) > MAX_DIFF_CHARS:
            diff_out += f"\n... [diff truncated — {len(diff) - MAX_DIFF_CHARS} more chars]"

        return {
            "id": p["id"],
            "subject": subject,
            "date": p.get("date", ""),
            "submitter": p.get("submitter", {}).get("name", "Unknown"),
            "submitter_email": p.get("submitter", {}).get("email", ""),
            "state": p.get("state", ""),
            "subsystem": subsystem,
            "files_changed": files_changed[:40],       # cap list length
            "diff_stats": stats,
            "abi_flags": abi_flags,
            "has_abi_concerns": len(abi_flags) > 0,
            "memory_leak_flags": memory_leak_flags,
            "has_memory_leak_concerns": len(memory_leak_flags) > 0,
            "commit_message": content[:2000] if content else "",
            "diff": diff_out,
            "web_url": p.get("web_url", ""),
        }

    # ------------------------------------------------------------------
    elif tool_name == "get_series_patches":
        series_id = int(tool_input["series_id"])
        series = fetch_series_by_id(series_id)

        cover = series.get("cover_letter") or {}
        patches = series.get("patches", [])

        return {
            "series_id": series_id,
            "name": series.get("name", ""),
            "date": series.get("date", ""),
            "version": series.get("version", 1),
            "submitter": series.get("submitter", {}).get("name", "Unknown"),
            "submitter_email": series.get("submitter", {}).get("email", ""),
            "total_patches": series.get("total", len(patches)),
            "cover_letter_subject": cover.get("name", ""),
            "cover_letter_excerpt": (cover.get("content") or "")[:1500],
            "patches": [
                {
                    "id": pp.get("id"),
                    "subject": pp.get("name", ""),
                    "web_url": pp.get("web_url", ""),
                }
                for pp in patches
            ],
        }

    # ------------------------------------------------------------------
    else:
        return {"error": f"Unknown tool: {tool_name}"}
