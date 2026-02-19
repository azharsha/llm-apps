#!/usr/bin/env python3
"""
LKML Patch Summary Agent — AI-powered Linux kernel patch analysis.

Fetches recent patches from patchwork.kernel.org, uses Claude to detect
subsystems, summarise technical changes, flag ABI / breaking-change risks,
and produces a terminal digest + an HTML report.

Usage:
    python main.py
    python main.py --limit 20 --days 2
    python main.py --project linux-usb --days 1
    python main.py --project netdev --subsystem "Wi-Fi" --limit 30
    python main.py --list-projects
"""
import sys
import os
import argparse
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ANTHROPIC_API_KEY, DEFAULT_LIMIT, DEFAULT_DAYS_BACK
from agents.orchestrator import run_analysis
from digest.generator import generate_html_report

console = Console(stderr=False)


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold green]LKML Patch Summary Agent[/bold green]\n"
            "[dim]AI-powered Linux kernel patch digest — powered by Claude[/dim]",
            border_style="green",
            padding=(0, 2),
        )
    )


def cmd_list_projects() -> None:
    """Print a table of all Patchwork projects and exit."""
    from fetcher.patchwork import fetch_projects

    console.print("\nFetching project list from patchwork.kernel.org…\n")
    projects = fetch_projects(limit=200)
    projects.sort(key=lambda p: p.get("name", "").lower())

    table = Table(
        title="Patchwork Projects  (use link_name with --project)",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("--project value", style="bold yellow", min_width=28)
    table.add_column("Full name", style="white")

    for p in projects:
        table.add_row(
            str(p.get("id", "")),
            p.get("link_name", ""),
            p.get("name", ""),
        )

    console.print(table)
    console.print(
        "\n[dim]Example: python main.py --project linux-usb --days 2[/dim]\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LKML Patch Summary Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                                  # last day, all subsystems\n"
            "  python main.py --project linux-usb              # USB subsystem only\n"
            "  python main.py --project netdev --days 2        # networking, 2 days\n"
            "  python main.py --project dri-devel --limit 30  # DRM/GPU patches\n"
            "  python main.py --list-projects                  # show all project names\n"
            "  python main.py --subsystem USB --limit 20       # keyword filter within results\n"
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Max patches to fetch (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--days", type=float, default=DEFAULT_DAYS_BACK,
        help=f"Days of history to cover (default: {DEFAULT_DAYS_BACK}, fractional OK)",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help=(
            "Patchwork project link_name to filter by, e.g. 'linux-usb', "
            "'netdev', 'dri-devel', 'linux-scsi'. "
            "Run --list-projects to see all options."
        ),
    )
    parser.add_argument(
        "--subsystem", type=str, default=None,
        help=(
            "Keyword filter applied on top of --project results. "
            "Matches against patch subjects case-insensitively, e.g. "
            "'EHCI', 'iwlwifi', 'btrfs'. Useful when a project covers "
            "multiple drivers and you want just one."
        ),
    )
    parser.add_argument(
        "--list-projects", action="store_true",
        help="Print all available Patchwork project names and exit.",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="HTML output file path (default: lkml_digest_YYYYMMDD.html)",
    )
    args = parser.parse_args()

    # ── list-projects shortcut — no API key needed ────────────────────────
    if args.list_projects:
        cmd_list_projects()
        return

    if not ANTHROPIC_API_KEY:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY is not set.\n"
            "Create a [bold].env[/bold] file with: ANTHROPIC_API_KEY=sk-..."
        )
        sys.exit(1)

    # ── Pre-flight: validate project name ────────────────────────────────
    if args.project:
        from fetcher.patchwork import fetch_patches as _fp
        probe = _fp(limit=1, days_back=30, project=args.project)
        if not probe:
            console.print(
                f"\n[red]Error:[/red] No patches found for project=[bold]{args.project!r}[/bold].\n"
                "The --project value must match a Patchwork link_name exactly.\n\n"
                "Common GPU/graphics names:\n"
                "  [yellow]dri-devel[/yellow]    — main DRM mailing list\n"
                "  [yellow]intel-gfx[/yellow]   — Intel i915 / Xe\n"
                "  [yellow]amd-gfx[/yellow]     — AMD RDNA / AMDGPU  (check --list-projects)\n\n"
                "Run [bold]python main.py --list-projects[/bold] to see every valid name."
            )
            sys.exit(1)

    print_banner()

    parts = [f"last [bold]{args.days}[/bold] day(s)"]
    if args.project:
        parts.append(f"project=[cyan]{args.project}[/cyan]")
    if args.subsystem:
        parts.append(f"subsystem keyword=[cyan]{args.subsystem}[/cyan]")
    parts.append(f"limit=[bold]{args.limit}[/bold]")
    console.print(f"\n  Fetching {', '.join(parts)}\n")

    result = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Initialising agent…", total=None)

        def on_progress(msg: str) -> None:
            progress.update(task, description=f"[dim]{msg}[/dim]")

        try:
            result = run_analysis(
                limit=args.limit,
                days_back=args.days,
                project=args.project,
                subsystem_filter=args.subsystem,
                progress_callback=on_progress,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
            sys.exit(0)
        except Exception as exc:
            console.print(f"\n[red]Analysis failed:[/red] {exc}")
            sys.exit(1)

    # ── Print digest to terminal ──────────────────────────────────────────
    console.print()
    console.print(Rule("[bold green]LKML DIGEST[/bold green]"))
    console.print()
    console.print(result.get("digest", "[yellow]No digest generated.[/yellow]"))
    console.print()
    console.print(Rule())

    stats = Text()
    stats.append(f"  Iterations: {result.get('iterations', 0)}", style="dim")
    stats.append("  ·  ", style="dim")
    stats.append(f"API calls: {len(result.get('tools_used', []))}", style="dim")
    stats.append("  ·  ", style="dim")
    stats.append(f"Patches fetched: {result.get('patches_fetched', 0)}", style="dim")
    stats.append("  ·  ", style="dim")
    stats.append(f"Series tracked: {result.get('series_count', 0)}", style="dim")
    console.print(stats)
    console.print()

    # ── Generate HTML report ──────────────────────────────────────────────
    report_date = date.today().strftime("%Y%m%d")
    slug = args.project or "all"
    output_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"lkml_digest_{slug}_{report_date}.html",
    )

    with console.status("[bold green]Generating HTML report…[/bold green]"):
        generate_html_report(result, output_path)

    console.print(f"[bold green]Report saved:[/bold green] {output_path}")


if __name__ == "__main__":
    main()
