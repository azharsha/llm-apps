"""
Main agentic loop for the LKML patch summary agent.

The Claude model calls tools autonomously until it has enough data to
produce a structured digest, then returns the final text.
"""
import json
import anthropic

from config import MODEL, ANTHROPIC_API_KEY, MAX_AGENT_ITERATIONS, DEFAULT_LIMIT, DEFAULT_DAYS_BACK
from agents.tools import TOOL_SCHEMAS, dispatch_tool


SYSTEM_PROMPT = """You are an expert Linux kernel developer tasked with summarising recent LKML (Linux Kernel Mailing List) patches for a technical audience of kernel engineers and maintainers.

## Your Workflow

1. Call `fetch_recent_patches` to retrieve a batch of recent patches.
2. Group patches by their `series_ids` — patches that share a series belong together.
3. For each unique series, call `get_series_patches` to understand the full scope.
4. For each series (or for standalone patches with no series), call `get_patch_details` on the **most representative patch** (the cover letter patch, or patch 1/N, or a single-patch submission).  You may also call it on additional patches when the series is large or concerns are detected.
5. Once you have analysed all series, write the digest.

## Per-Patch Analysis

For every patch or series, determine:

| Field         | What to extract                                                         |
|---------------|-------------------------------------------------------------------------|
| Subsystem     | Top-level kernel area (use detected value, refine if needed)            |
| Type          | bug-fix / new-feature / cleanup / refactor / doc-only                   |
| Summary       | 2–3 sentences describing *what* changes and *why*                       |
| Key files     | Most important changed files (not the full list)                        |
| Impact        | Minor / Moderate / Major (based on scope, subsystem, diff size)         |
| Flags         | ABI concerns, security implications, breaking changes, regressions risk |
| Memory Leaks  | Potential memory or resource leaks introduced or fixed by the patch     |

## Memory Leak Analysis

When analysing each patch diff, check for potential memory or resource leaks:

- **Allocations without free on all paths**: If `kmalloc`, `kzalloc`, `vmalloc`, `kcalloc`, `devm_kmalloc`, etc. are added, verify that every error path (early `return`, `goto`) frees the allocated memory before returning.
- **Removed deallocations**: If `kfree`, `vfree`, `kvfree`, or `kmem_cache_free` calls are deleted, determine whether the memory is now freed elsewhere or is genuinely leaked.
- **Reference count imbalances**: Check for removed `put_device`, `kobject_put`, `kref_put`, `of_node_put`, `dev_put`, or similar calls where the matching `get` is still present.
- **Removed error-path labels**: If a `goto` target like `err_free:` or `cleanup:` is removed, check whether its cleanup code was moved or simply dropped.
- **sk_buff leaks**: Removed `kfree_skb` / `consume_skb` on a non-success path is a common networking leak.
- **Firmware / IRQ / DMA**: Check that `release_firmware`, `free_irq`, and `dma_free_*` calls are preserved on all error and teardown paths.
- Use the `memory_leak_flags` field from `get_patch_details` as a starting point, but also reason holistically about the diff — static patterns may miss context-dependent leaks or produce false positives.
- If the patch *fixes* a leak, say so clearly in the Memory Leaks field.

## Output Format

After finishing all analysis, write your digest inside these exact delimiters:

=== LKML DIGEST BEGIN ===
Date: <today's date>
Patches Fetched: <N>
Series Summarised: <N>

---
### [SUBSYSTEM] — <concise title>
**Submitter**: <Name> <<email>>
**Type**: <bug-fix | new-feature | cleanup | refactor | doc-only>
**Impact**: <Minor | Moderate | Major>
**Patches**: <N> patch(es)   **State**: <state>
**Web**: <patchwork URL>

**Summary**:
<2–3 sentences — technical, precise, no fluff>

**Key files**: `<file1>`, `<file2>`, …

**Flags**: <NONE — or bullet list of ABI/security concerns>

**Memory Leaks**: <NONE — or bullet list of potential memory/resource leak concerns>

---
(repeat for every series / standalone patch)

=== LKML DIGEST END ===

## Guidelines
- Be technically precise — this is for kernel developers, not end users.
- Prefer the detected `subsystem` field but override it when you know better.
- Flag anything touching `include/uapi/` (userspace ABI), removed `EXPORT_SYMBOL`, changed ioctls, or explicit mentions of breaking changes.
- Note security implications when patches touch memory management, LSM, crypto, or privilege paths.
- For every patch that adds allocations or removes frees, reason about leak safety on all exit paths and report findings under **Memory Leaks**.
- If a series has a cover letter, use it for the high-level summary; the individual patches give you details.
- If `get_patch_details` returns an error or an empty diff, note the patch briefly and continue.
- Do NOT fabricate details — only summarise what the tool results actually say.
"""


def run_analysis(
    limit: int = DEFAULT_LIMIT,
    days_back: float = DEFAULT_DAYS_BACK,
    project: str = None,
    subsystem_filter: str = None,
    progress_callback=None,
) -> dict:
    """
    Run the patch-summary agentic loop.

    Args:
        limit:             Max patches to fetch from the API.
        days_back:         How many days of history to cover.
        project:           Patchwork project link_name to restrict to (e.g. 'linux-usb').
        subsystem_filter:  Optional keyword; agent is instructed to focus only on
                           patches whose subject/files match this string.
        progress_callback: Optional callable(str) for UI progress messages.

    Returns:
        dict with keys: digest, tools_used, iterations, patches_fetched, series_count.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build a focused user prompt from the supplied filters
    scope_parts = [f"the last {days_back} day(s)"]
    fetch_args = [f"up to {limit} patches"]
    if project:
        fetch_args.append(f"project='{project}'")
    if subsystem_filter:
        fetch_args.append(
            f"then concentrate only on patches related to '{subsystem_filter}' "
            "(filter by subject / file paths / driver name — skip unrelated patches)"
        )

    messages = [
        {
            "role": "user",
            "content": (
                f"Please analyse Linux kernel patches from {', '.join(scope_parts)} "
                f"on patchwork.kernel.org ({', '.join(fetch_args)}). "
                "Group them by series, analyse each one, flag any ABI or breaking "
                "changes, and produce a complete technical digest."
            ),
        }
    ]

    tools_used: list[str] = []
    iteration = 0
    final_text = ""
    patches_fetched = 0
    series_seen: set[int] = set()

    while iteration < MAX_AGENT_ITERATIONS:
        iteration += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        text_parts = []
        tool_use_blocks = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        if text_parts:
            final_text = "\n".join(text_parts)

        # No tool calls → agent is done
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # Execute each tool call
        tool_results = []
        for tb in tool_use_blocks:
            if progress_callback:
                progress_callback(f"Tool: {tb.name}({_fmt_input(tb.input)})")

            tools_used.append(tb.name)

            # Inject project / subsystem_filter into fetch calls if not already set
            tool_input = dict(tb.input)
            if tb.name == "fetch_recent_patches":
                if project and not tool_input.get("project"):
                    tool_input["project"] = project
                if subsystem_filter and not tool_input.get("subsystem_filter"):
                    tool_input["subsystem_filter"] = subsystem_filter

            result_json = dispatch_tool(tb.name, tool_input)

            # Track lightweight stats
            try:
                parsed = json.loads(result_json)
                if tb.name == "fetch_recent_patches":
                    patches_fetched += parsed.get("count", 0)
                elif tb.name == "get_series_patches":
                    series_seen.add(tb.input.get("series_id"))
            except Exception:
                pass

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": result_json,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return {
        "digest": final_text,
        "tools_used": tools_used,
        "iterations": iteration,
        "patches_fetched": patches_fetched,
        "series_count": len(series_seen),
    }


def _fmt_input(inp: dict) -> str:
    """Compact single-line representation of tool inputs for progress display."""
    parts = [f"{k}={v}" for k, v in inp.items()]
    text = ", ".join(parts)
    return text[:60] + "…" if len(text) > 60 else text
