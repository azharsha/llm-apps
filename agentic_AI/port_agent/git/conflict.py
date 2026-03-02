"""
Conflict parsing, display, and interactive resolution for port_agent.

ask_user_to_resolve() is where the agentic loop pauses: it prints conflict
content to the terminal using Rich, then calls input() to block until the
user responds. dispatch_tool calls this synchronously.
"""
import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

console = Console()


# ---------------------------------------------------------------------------
# Conflict parsing
# ---------------------------------------------------------------------------

def parse_conflicts(repo_path: str, conflicted_files: list[str]) -> list[dict]:
    """
    For each conflicted file, read content and extract conflict sections.

    Returns list of:
        {
          file: str,
          full_content: str,    # entire file (capped at 8000 chars)
          sections: list[{
              ours_label: str,
              ours: str,        # content between <<<<<<< and =======
              theirs: str,      # content between ======= and >>>>>>>
              context_before: str,
              context_after: str,
          }]
        }
    """
    results = []
    for entry in conflicted_files:
        # Accept both plain path strings and the dict form from manual_apply_needed
        # {"file": path, "rej_content": ...}
        rel_path = entry.get("file") if isinstance(entry, dict) else entry
        abs_path = Path(repo_path) / rel_path
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            results.append({
                "file": rel_path,
                "full_content": "",
                "sections": [],
                "error": "file not found",
            })
            continue

        sections = _extract_conflict_sections(content)
        results.append({
            "file": rel_path,
            "full_content": content[:8000],
            "sections": sections,
        })
    return results


def _extract_conflict_sections(content: str) -> list[dict]:
    """Parse <<<<<<< / ======= / >>>>>>> blocks from file content."""
    pattern = re.compile(
        r"<{7} ([^\n]+)\n(.*?)={7}\n(.*?)>{7}[^\n]*",
        re.DOTALL,
    )
    lines = content.splitlines()
    sections = []
    for m in pattern.finditer(content):
        start_pos = m.start()
        line_num = content[:start_pos].count("\n")
        block_lines = m.group(0).count("\n")
        ctx_start = max(0, line_num - 5)
        ctx_end = min(len(lines), line_num + block_lines + 5)
        sections.append({
            "ours_label": m.group(1),
            "ours": m.group(2).strip(),
            "theirs": m.group(3).strip(),
            "context_before": "\n".join(lines[ctx_start:line_num]),
            "context_after": "\n".join(lines[line_num + block_lines:ctx_end]),
        })
    return sections


def format_conflict_for_display(conflict_dict: dict) -> str:
    """Format a conflict dict into a human-readable string for Claude."""
    lines = [f"File: {conflict_dict['file']}"]
    for i, sec in enumerate(conflict_dict.get("sections", []), 1):
        lines.append(f"\n--- Conflict #{i} ---")
        if sec.get("context_before"):
            lines.append(f"Context before:\n{sec['context_before']}")
        lines.append(f"OURS (downstream, {sec.get('ours_label', 'HEAD')}):\n{sec['ours']}")
        lines.append(f"THEIRS (upstream):\n{sec['theirs']}")
        if sec.get("context_after"):
            lines.append(f"Context after:\n{sec['context_after']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Resolution application
# ---------------------------------------------------------------------------

def apply_resolution(repo_path: str, file_path: str, resolved_content: str) -> dict:
    """
    Write resolved_content to file_path. Does NOT stage — caller must
    call repo.stage_file() afterward.
    """
    abs_path = Path(repo_path) / file_path
    try:
        if "<<<<<<" in resolved_content:
            return {
                "success": False,
                "error": "Conflict markers still present in resolved content",
            }
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(resolved_content, encoding="utf-8")
        return {"success": True, "file": file_path}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Interactive user prompt (pauses the agentic loop)
# ---------------------------------------------------------------------------

# Set to True by main.py when --non-interactive flag is used.
# In non-interactive mode, Claude's suggestion is auto-accepted.
NON_INTERACTIVE = False

def ask_user_to_resolve(
    repo_path: str,
    conflict_file: str,
    conflict_content: str,
    claude_suggestion: str,
    commit_subject: str,
) -> dict:
    """
    INTERACTIVE: Pause the agentic loop and ask the user how to resolve
    a conflict. Called from dispatch_tool when Claude invokes
    ask_user_to_resolve_conflict.

    Returns:
        {
          action: "accept" | "modify" | "provide" | "skip_commit" | "abort",
          resolved_content: str | None,
          user_note: str,
        }
    """
    console.print()
    console.rule("[bold yellow]Conflict Resolution Required[/bold yellow]")
    console.print(f"[dim]Commit:[/dim] {commit_subject}")
    console.print(f"[dim]File:[/dim]   {conflict_file}")
    console.print()

    # Non-interactive mode: auto-accept Claude's suggestion without prompting
    if NON_INTERACTIVE:
        console.print(Panel(
            Syntax(claude_suggestion[:3000], "c", theme="monokai", line_numbers=False),
            title="[green]Claude's Resolution (auto-accepted in non-interactive mode)[/green]",
            expand=False,
        ))
        console.print("[dim]Non-interactive: accepting Claude's resolution automatically.[/dim]")
        return {
            "action": "accept",
            "resolved_content": claude_suggestion,
            "user_note": "auto-accepted (non-interactive mode)",
        }

    # Show conflict content
    console.print(Panel(
        Syntax(conflict_content[:3000], "c", theme="monokai", line_numbers=False),
        title="[red]Conflict Markers[/red]",
        expand=False,
    ))

    # Show Claude's suggestion
    console.print()
    console.print(Panel(
        Syntax(claude_suggestion[:3000], "c", theme="monokai", line_numbers=False),
        title="[green]Claude's Proposed Resolution[/green]",
        expand=False,
    ))

    console.print()
    console.print("[bold]Options:[/bold]")
    console.print("  [green][A][/green] Accept Claude's suggestion")
    console.print("  [yellow][M][/yellow] Modify Claude's suggestion (opens editor hint)")
    console.print("  [blue][P][/blue] Paste your own resolution")
    console.print("  [red][S][/red] Skip this commit (cherry-pick --abort)")
    console.print("  [red][Q][/red] Abort entire porting session")
    console.print()

    choice = Prompt.ask(
        "Your choice",
        choices=["a", "m", "p", "s", "q", "A", "M", "P", "S", "Q"],
        default="A",
    ).lower()

    if choice == "a":
        user_note = Prompt.ask(
            "Add a note to the commit message about this resolution? (leave blank to skip)",
            default="",
        )
        return {
            "action": "accept",
            "resolved_content": claude_suggestion,
            "user_note": user_note,
        }

    elif choice == "m":
        console.print()
        console.print("[yellow]Edit Claude's suggestion. Paste the modified content below.[/yellow]")
        console.print("[dim]Enter an empty line followed by '###END###' to finish.[/dim]")
        resolved = _read_multiline_input("###END###")
        if not resolved.strip():
            console.print("[red]No content provided. Falling back to Claude's suggestion.[/red]")
            resolved = claude_suggestion
        user_note = Prompt.ask("Note for commit message", default="")
        return {
            "action": "modify",
            "resolved_content": resolved,
            "user_note": user_note,
        }

    elif choice == "p":
        console.print()
        console.print("[blue]Paste your resolution below.[/blue]")
        console.print("[dim]Enter an empty line followed by '###END###' to finish.[/dim]")
        resolved = _read_multiline_input("###END###")
        user_note = Prompt.ask("Note for commit message", default="")
        return {
            "action": "provide",
            "resolved_content": resolved,
            "user_note": user_note,
        }

    elif choice == "s":
        console.print("[red]Skipping this commit.[/red]")
        reason = Prompt.ask("Reason for skipping", default="Manual skip during porting")
        return {
            "action": "skip_commit",
            "resolved_content": None,
            "user_note": reason,
        }

    else:  # q
        console.print("[bold red]Aborting porting session.[/bold red]")
        return {
            "action": "abort",
            "resolved_content": None,
            "user_note": "User aborted session",
        }


def _read_multiline_input(terminator: str) -> str:
    """Read lines from stdin until terminator line is encountered."""
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == terminator:
            break
        lines.append(line)
    return "\n".join(lines)
