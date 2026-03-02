"""
port_agent — Port Linux kernel code directories to a downstream kernel tree.

Usage (explicit paths):
    python main.py \\
        --upstream /path/to/linux \\
        --downstream /path/to/chromeos-kernel \\
        --upstream-branch main \\
        --downstream-branch chromeos-6.6 \\
        --dirs drivers/gpu/drm drivers/gpu/drm/intel \\
        --work-branch port/drm-sync-20250227 \\
        [--build-cmd "make -j$(nproc) drivers/gpu/drm/"] \\
        [--max-commits 50] \\
        [--dry-run]

Usage (named project from projects.yaml):
    python main.py --project chromeos-6.6 [overrides...]
    python main.py --list-projects
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

import config
from agents.orchestrator import run_porting_session
from git import repo as repo_mod
from report.generator import generate_html_report

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Port Linux kernel code directories to a downstream kernel using Claude AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Project registry ────────────────────────────────────────────────────
    proj_group = parser.add_argument_group("project registry")
    proj_group.add_argument("--project", metavar="NAME",
                            help="Named project from projects.yaml (sets path/branch/dirs defaults)")
    proj_group.add_argument("--projects-file", metavar="FILE",
                            help="Path to projects YAML file (default: ./projects.yaml)")
    proj_group.add_argument("--list-projects", action="store_true",
                            help="List all projects defined in projects.yaml and exit")

    # ── Repo paths (required unless supplied via --project) ─────────────────
    parser.add_argument("--upstream", metavar="PATH",
                        help="Absolute path to the upstream Linux kernel repo")
    parser.add_argument("--downstream", metavar="PATH",
                        help="Absolute path to the downstream kernel repo")
    parser.add_argument("--upstream-branch", default=None, metavar="BRANCH",
                        help="Branch in the upstream repo (default: main)")
    parser.add_argument("--downstream-branch", default=None, metavar="BRANCH",
                        help="Branch in the downstream repo (default: main)")
    parser.add_argument("--dirs", nargs="+", metavar="DIR",
                        help="Kernel subdirectories to port (e.g. drivers/gpu/drm)")

    # ── Session options ─────────────────────────────────────────────────────
    parser.add_argument("--work-branch", metavar="BRANCH",
                        help="Name for the porting work branch (default: port/sync-<date>)")
    parser.add_argument("--build-cmd", metavar="CMD", default=None,
                        help="Build command to validate each commit (e.g. 'make -j4 drivers/')")
    parser.add_argument("--max-commits", type=int, default=config.MAX_COMMITS_PER_SESSION,
                        metavar="N", help=f"Max commits to port (default: {config.MAX_COMMITS_PER_SESSION})")
    parser.add_argument("--since-tag", metavar="TAG", default=None,
                        help=(
                            "Upstream git tag to use as the lower bound for commit search "
                            "(e.g. 'v6.6-rc7'). Required when upstream and downstream repos "
                            "do not share git history (cross-repo porting like linux → chromeos)."
                        ))
    parser.add_argument("--dry-run", action="store_true",
                        help="Identify commits to port without applying them")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Auto-accept Claude's conflict resolutions without pausing for user input")
    return parser.parse_args()


def resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    """
    Merge project-registry defaults into args, then validate completeness.

    Priority (highest → lowest):
      1. Explicit CLI flags
      2. Named project in projects.yaml (--project NAME)
      3. Built-in defaults (upstream/downstream-branch → "main")
    """
    # Only load projects.yaml when the user actually asked for it.
    # Importing without --project/--list-projects must never require pyyaml.
    needs_projects = args.project or args.list_projects
    if needs_projects:
        from projects import load_projects
        projects = load_projects(args.projects_file)
    else:
        projects = {}

    # ── --list-projects ─────────────────────────────────────────────────────
    if args.list_projects:
        _print_projects(projects)
        sys.exit(0)

    # ── --project NAME ──────────────────────────────────────────────────────
    if args.project:
        if not projects:
            console.print(
                "[bold red]Error:[/bold red] No projects file found. "
                "Create projects.yaml (see projects.yaml.example)."
            )
            sys.exit(1)
        if args.project not in projects:
            console.print(f"[bold red]Error:[/bold red] Project '[cyan]{args.project}[/cyan]' not found.")
            _print_projects(projects)
            sys.exit(1)

        proj = projects[args.project]

        # Fill in only what was not explicitly supplied on the CLI
        if not args.upstream:
            args.upstream = proj.upstream_path
        if not args.downstream:
            args.downstream = proj.downstream_path
        if args.upstream_branch is None:
            args.upstream_branch = proj.upstream_branch
        if args.downstream_branch is None:
            args.downstream_branch = proj.downstream_branch
        if not args.dirs:
            args.dirs = list(proj.dirs)
        if not args.build_cmd and proj.build_cmd:
            args.build_cmd = proj.build_cmd
        if not args.since_tag and proj.since_tag:
            args.since_tag = proj.since_tag
        # Use work_branch_prefix to generate work_branch only if not explicitly set
        if not args.work_branch and proj.work_branch_prefix:
            args.work_branch = f"{proj.work_branch_prefix}-{datetime.now().strftime('%Y%m%d')}"

    # ── Apply built-in defaults for branch names ────────────────────────────
    if args.upstream_branch is None:
        args.upstream_branch = "main"
    if args.downstream_branch is None:
        args.downstream_branch = "main"

    # ── Validate completeness ───────────────────────────────────────────────
    missing = []
    if not args.upstream:
        missing.append("--upstream")
    if not args.downstream:
        missing.append("--downstream")
    if not args.dirs:
        missing.append("--dirs")
    if missing:
        console.print(
            f"[bold red]Error:[/bold red] Missing required arguments: "
            f"[cyan]{', '.join(missing)}[/cyan]\n"
            "Provide them directly or via [cyan]--project NAME[/cyan] from projects.yaml."
        )
        sys.exit(1)

    return args


def _print_projects(projects: dict) -> None:
    """Pretty-print all defined projects."""
    if not projects:
        console.print("[yellow]No projects defined.[/yellow] "
                      "Create a projects.yaml file (see projects.yaml.example).")
        return

    table = Table(title="Defined Projects", border_style="cyan", header_style="bold cyan")
    table.add_column("Name", style="green")
    table.add_column("Downstream", style="white")
    table.add_column("Branch", style="cyan")
    table.add_column("Dirs", style="yellow")
    table.add_column("Build cmd", style="dim")

    for name, proj in projects.items():
        table.add_row(
            name,
            proj.downstream_path,
            proj.downstream_branch,
            ", ".join(proj.dirs[:3]) + (" …" if len(proj.dirs) > 3 else ""),
            proj.build_cmd or "(checkpatch only)",
        )

    console.print(table)


def validate_env() -> None:
    if not config.ANTHROPIC_API_KEY:
        console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY not set.")
        console.print("Copy .env.example to .env and add your key.")
        sys.exit(1)


def validate_repos(upstream: str, downstream: str) -> None:
    for label, path in [("upstream", upstream), ("downstream", downstream)]:
        if not Path(path).is_dir():
            console.print(f"[bold red]Error:[/bold red] {label} path not found: {path}")
            sys.exit(1)
        git_dir = Path(path) / ".git"
        if not git_dir.exists():
            console.print(f"[bold red]Error:[/bold red] {path} is not a git repository")
            sys.exit(1)


def check_or_create_work_branch(
    downstream_path: str,
    work_branch: str,
    downstream_branch: str,
) -> None:
    """Create work branch if it doesn't exist, else offer to resume."""
    if repo_mod.branch_exists(downstream_path, work_branch):
        current = repo_mod.get_current_branch(downstream_path)
        if current != work_branch:
            console.print(f"[yellow]Work branch '{work_branch}' already exists.[/yellow]")
            resume = Confirm.ask("Checkout and continue on existing work branch?", default=True)
            if resume:
                repo_mod.checkout_branch(downstream_path, work_branch)
            else:
                console.print("Aborting. Choose a different --work-branch name.")
                sys.exit(0)
    else:
        if not repo_mod.branch_exists(downstream_path, downstream_branch):
            console.print(f"[red]Downstream branch '{downstream_branch}' not found.[/red]")
            sys.exit(1)
        console.print(f"Creating work branch [cyan]{work_branch}[/cyan] from [cyan]{downstream_branch}[/cyan]...")
        repo_mod.create_work_branch(downstream_path, work_branch, downstream_branch)


def check_session_state(downstream_path: str) -> dict | None:
    """Load existing porting_session.json if present."""
    state_file = Path(downstream_path) / "porting_session.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            return None
    return None


def save_session_state(downstream_path: str, result: dict) -> None:
    state_file = Path(downstream_path) / "porting_session.json"
    state = {
        "upstream": result.get("upstream_path"),
        "downstream": result.get("downstream_path"),
        "dirs": result.get("dirs"),
        "work_branch": result.get("work_branch"),
        "ported": result.get("ported_commits", []),
        "skipped": result.get("skipped_commits", []),
        "last_run": result.get("timestamp"),
    }
    state_file.write_text(json.dumps(state, indent=2, default=str))


def prompt_no_build_cmd() -> bool:
    """Warn user that no build command was provided. Return True to continue."""
    console.print()
    console.print(Panel(
        "[yellow]No --build-cmd provided.[/yellow]\n"
        "Compilation will NOT be validated — only checkpatch.pl will run.\n"
        "Build errors will go undetected until you compile manually.",
        title="Build Validation Warning",
        border_style="yellow",
    ))
    return Confirm.ask("Continue with checkpatch-only validation?", default=False)


def main() -> None:
    args = parse_args()
    args = resolve_args(args)

    validate_env()
    validate_repos(args.upstream, args.downstream)

    work_branch = args.work_branch or f"port/sync-{datetime.now().strftime('%Y%m%d')}"

    console.print(Panel.fit(
        "[bold cyan]port_agent[/bold cyan] — Linux Kernel Porting Tool\n"
        f"[dim]Powered by {config.MODEL}[/dim]",
        border_style="cyan",
    ))
    console.print()
    console.print(f"Upstream:   [green]{args.upstream}[/green] @ [cyan]{args.upstream_branch}[/cyan]")
    console.print(f"Downstream: [green]{args.downstream}[/green] @ [cyan]{args.downstream_branch}[/cyan]")
    console.print(f"Dirs:       [yellow]{', '.join(args.dirs)}[/yellow]")
    console.print(f"Work branch:[cyan]{work_branch}[/cyan]")
    console.print(f"Max commits:[white]{args.max_commits}[/white]")
    if args.dry_run:
        console.print("[bold yellow]DRY RUN — no commits will be made[/bold yellow]")
    console.print()

    # Build command check
    build_cmd = args.build_cmd
    if not build_cmd and not args.dry_run:
        if args.non_interactive:
            console.print("[yellow]No --build-cmd — checkpatch-only validation (non-interactive: continuing automatically).[/yellow]")
        elif not prompt_no_build_cmd():
            console.print("Aborting. Supply --build-cmd to enable build validation.")
            sys.exit(0)

    # Check for existing session state
    existing_state = check_session_state(args.downstream)
    if existing_state and not args.dry_run:
        ported_count = len(existing_state.get("ported", []))
        skipped_count = len(existing_state.get("skipped", []))
        console.print(Panel(
            f"Found existing porting session:\n"
            f"  Ported:  {ported_count} commits\n"
            f"  Skipped: {skipped_count} commits\n"
            f"  Last run: {existing_state.get('last_run', 'unknown')}",
            title="[yellow]Session Resume Available[/yellow]",
            border_style="yellow",
        ))
        # The orchestrator handles resume implicitly via _get_already_ported_shas()
        # which reads cherry-pick attribution from git log

    # Create / checkout work branch
    if not args.dry_run:
        check_or_create_work_branch(args.downstream, work_branch, args.downstream_branch)

    # Configure interactivity
    if args.non_interactive:
        from git import conflict as _conflict_mod
        _conflict_mod.NON_INTERACTIVE = True
        console.print("[yellow]Non-interactive mode: Claude's conflict resolutions will be auto-accepted.[/yellow]")

    # Patch-based mode: no cross-repo fetch needed
    console.print("[dim]Using format-patch|am — no cross-repo fetch required.[/dim]")
    console.print()

    # Run the agentic porting session
    final_result: dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running port_agent...", total=None)

        def update_progress(msg: str) -> None:
            progress.update(task, description=msg)

        try:
            final_result = run_porting_session(
                upstream_path=args.upstream,
                downstream_path=args.downstream,
                upstream_branch=args.upstream_branch,
                downstream_branch=args.downstream_branch,
                dirs=args.dirs,
                work_branch=work_branch,
                build_cmd=build_cmd,
                max_commits=args.max_commits,
                since_tag=args.since_tag,
                dry_run=args.dry_run,
                progress_callback=update_progress,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
            sys.exit(0)
        except Exception as exc:
            console.print(f"\n[bold red]Fatal error:[/bold red] {exc}")
            raise

    # Add branch info to result for the report
    final_result["upstream_branch"] = args.upstream_branch
    final_result["downstream_branch"] = args.downstream_branch

    # Display summary
    console.print()
    console.rule("[bold green]Porting Complete[/bold green]")
    console.print()
    if final_result.get("summary"):
        console.print(Panel(
            final_result["summary"],
            title="Agent Summary",
            border_style="green",
        ))

    ported = final_result.get("ported_commits", [])
    skipped = final_result.get("skipped_commits", [])
    console.print(f"\n[green]Ported:[/green]  {len(ported)} commits")
    console.print(f"[yellow]Skipped:[/yellow] {len(skipped)} commits")
    console.print(f"[dim]Agent iterations:[/dim] {final_result.get('iterations', 0)}")

    # Save session state
    if not args.dry_run:
        save_session_state(args.downstream, final_result)
        console.print(f"\n[dim]Session state saved to {args.downstream}/porting_session.json[/dim]")

    # Generate HTML report
    report_name = f"porting_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_path = str(Path(args.downstream) / report_name)
    generate_html_report(final_result, output_path=report_path)
    console.print(f"[dim]HTML report:[/dim] [cyan]{report_path}[/cyan]")


if __name__ == "__main__":
    main()
