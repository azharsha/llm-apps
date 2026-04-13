"""CLI entry point for PoAgent §15.

Usage:
    python -m poagent [OPTIONS]
    poagent [OPTIONS]

[FINAL-H1] Exit codes:
    0 = PASS
    1 = FAIL
    2 = CONDITIONAL
    3 = INCOMPLETE
    4 = PREFLIGHT_FAIL
    5 = DRY_RUN_FAIL
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import uuid
from pathlib import Path

import structlog
import structlog.dev

from poagent.config import PoAgentConfig
from poagent.security.credentials import resolve_api_key
from poagent.security.signing import verify_report

log = structlog.get_logger(__name__)

# [FINAL-H1] Verdict → exit code map
VERDICT_EXIT_CODES: dict[str, int] = {
    "PASS": 0,
    "FAIL": 1,
    "CONDITIONAL": 2,
    "INCOMPLETE": 3,
    "PREFLIGHT_FAIL": 4,
    "DRY_RUN_FAIL": 5,
}


def _configure_logging(level: str) -> None:
    """Configure structlog with given log level."""
    import logging

    level_int = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=level_int,
        stream=sys.stderr,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the full CLI argument parser per PRD §15."""
    p = argparse.ArgumentParser(
        prog="poagent",
        description="Power-On Diagnostic Agent — autonomous board bring-up analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  PASS           All diagnostics passed
  1  FAIL           One or more critical failures
  2  CONDITIONAL    Issues present but board may function
  3  INCOMPLETE     Analysis could not fully complete
  4  PREFLIGHT_FAIL Pre-flight gate failure (board not ready)
  5  DRY_RUN_FAIL   Dry-run validation failed
""",
    )

    # ── Connection ──────────────────────────────────────────────────────────
    conn = p.add_argument_group("Connection")
    conn_ex = conn.add_mutually_exclusive_group()
    conn_ex.add_argument(
        "--host",
        metavar="HOST[:PORT]",
        help="SSH target (user@host or host). Port defaults to 22.",
    )
    conn_ex.add_argument(
        "--serial",
        metavar="DEVICE",
        help="Serial device path (e.g. /dev/ttyUSB0). Mutually exclusive with --host.",
    )
    conn.add_argument(
        "--port",
        type=int,
        default=22,
        metavar="PORT",
        help="SSH port (default: 22). Ignored when --serial is used.",
    )
    conn.add_argument(
        "--baud",
        type=int,
        default=115200,
        metavar="BAUD",
        help="Serial baud rate (default: 115200). Only used with --serial.",
    )
    conn.add_argument(
        "--ssh-key",
        metavar="PATH",
        help="Path to SSH private key. Falls back to ~/.ssh/id_rsa.",
    )
    conn.add_argument(
        "--ssh-user",
        metavar="USER",
        default="root",
        help="SSH username (default: root).",
    )
    conn.add_argument(
        "--ssh-password",
        metavar="PASSWORD",
        help="SSH password. Prefer --ssh-key or keyring.",
    )

    # ── Board / DTS ──────────────────────────────────────────────────────────
    board = p.add_argument_group("Board configuration")
    board.add_argument(
        "--dts",
        metavar="PATH",
        help="Path to board .dts file. Required unless --dry-run --validate-overlay.",
    )
    board.add_argument(
        "--overlay",
        metavar="PATH",
        help="Path to PoAgent overlay .json/.yaml file.",
    )
    board.add_argument(
        "--board-name",
        metavar="NAME",
        help="Board identifier for lock file and report naming.",
    )
    board.add_argument(
        "--confirm-overlay",
        choices=["interactive", "pre_validated", "strict"],
        default="interactive",
        help="Overlay confirmation mode [FINAL-S5] (default: interactive).",
    )

    # ── Subsystem selection ──────────────────────────────────────────────────
    domain = p.add_argument_group("Domain/subsystem selection")
    domain.add_argument(
        "--subsystem",
        metavar="DOMAIN",
        action="append",
        dest="subsystems",
        help=(
            "Run only specified domain(s). Can be repeated. "
            "Valid: power_clocking, compute_memory, storage, highspeed_serial, "
            "display_graphics, networking, audio, lowspeed_interface, "
            "security_crypto, sensors_misc."
        ),
    )

    # ── Run modes ────────────────────────────────────────────────────────────
    modes = p.add_argument_group("Run modes")
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DTS + overlay without connecting to board. Exits 0 or 5.",
    )
    modes.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a previous interrupted run by run_id.",
    )
    modes.add_argument(
        "--reanalyze",
        action="store_true",
        help="Re-run triage + report from cached Phase 2 results (no board I/O).",
    )
    modes.add_argument(
        "--force-resume",
        action="store_true",
        help="Resume even if board lock from previous run is stale.",
    )
    modes.add_argument(
        "--allow-destructive-tests",
        action="store_true",
        help="Enable destructive tests (memtester, fio). CAUTION: may corrupt data.",
    )
    modes.add_argument(
        "--unsafe-shutdown-mode",
        choices=["ci_mode", "production_mode"],
        default="production_mode",
        help="Shutdown safety mode (default: production_mode).",
    )

    # ── Watchdog ─────────────────────────────────────────────────────────────
    wdt = p.add_argument_group("Watchdog keepalive [LAST-C1]")
    wdt.add_argument(
        "--watchdog-keepalive",
        choices=["auto", "warn", "disable"],
        default="warn",
        metavar="{auto,warn,disable}",
        help=(
            "Watchdog keepalive mode. auto=spawn keepalive thread (limits SSH to 2), "
            "warn=detect + warn only, disable=write V to stop watchdog (default: warn)."
        ),
    )

    # ── Validation utilities ─────────────────────────────────────────────────
    utils = p.add_argument_group("Validation utilities")
    utils.add_argument(
        "--validate-overlay",
        metavar="PATH",
        help="Validate an overlay file and exit. Returns 0 on valid, 1 on invalid.",
    )
    utils.add_argument(
        "--verify-report",
        metavar="PATH",
        help="Verify HMAC-SHA-256 signature of an HTML report and exit.",
    )

    # ── Spec ingestion ───────────────────────────────────────────────────────
    spec = p.add_argument_group("Spec ingestion")
    spec.add_argument(
        "--spec-pdf",
        metavar="PATH",
        help="Path to board specification PDF. Ingested before analysis.",
    )
    spec.add_argument(
        "--spec-csv",
        metavar="PATH",
        help="Path to rail/power-spec CSV. Merged with overlay.",
    )
    spec.add_argument(
        "--spec-page-range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Page range for --spec-pdf (1-based inclusive, e.g. 1 50).",
    )

    # ── Batch / fleet ────────────────────────────────────────────────────────
    batch = p.add_argument_group("Batch / fleet mode [§16]")
    batch.add_argument(
        "--batch",
        action="store_true",
        help="Run in batch/fleet mode. Requires --fleet-csv.",
    )
    batch.add_argument(
        "--fleet-csv",
        metavar="PATH",
        help="CSV with fleet board definitions. Used with --batch.",
    )
    batch.add_argument(
        "--fleet-concurrency",
        type=int,
        default=4,
        metavar="N",
        help="Number of parallel boards in fleet mode (default: 4).",
    )

    # ── Output ───────────────────────────────────────────────────────────────
    out = p.add_argument_group("Output")
    out.add_argument(
        "--output-dir",
        metavar="DIR",
        default="/var/log/poagent",
        help="Directory for reports and logs (default: /var/log/poagent).",
    )
    out.add_argument(
        "--run-id",
        metavar="UUID",
        help="Explicit run ID (UUID). Auto-generated if omitted.",
    )
    out.add_argument(
        "--json-only",
        action="store_true",
        help="Skip HTML report, output JSON report only.",
    )
    out.add_argument(
        "--no-sign",
        action="store_true",
        help="Skip HMAC-SHA-256 report signing.",
    )

    # ── LLM / API ────────────────────────────────────────────────────────────
    llm = p.add_argument_group("LLM / API")
    llm.add_argument(
        "--api-key",
        metavar="KEY",
        help="Anthropic API key. Falls back to ANTHROPIC_API_KEY env or keyring.",
    )
    llm.add_argument(
        "--model",
        metavar="MODEL",
        default="claude-sonnet-4-6",
        help="Claude model to use (default: claude-sonnet-4-6).",
    )
    llm.add_argument(
        "--agent-timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Per-domain agent wall-clock timeout in seconds (default: 120).",
    )
    llm.add_argument(
        "--max-agent-iterations",
        type=int,
        default=10,
        metavar="N",
        help="Max LLM tool-use iterations per domain agent (default: 10).",
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    log_grp = p.add_argument_group("Logging")
    log_grp.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log verbosity (default: INFO).",
    )
    log_grp.add_argument(
        "--log-dir",
        metavar="DIR",
        help="Override log directory (default: --output-dir/logs).",
    )

    return p


# ── Utility sub-commands ──────────────────────────────────────────────────────

def _cmd_validate_overlay(path: str) -> int:
    """--validate-overlay PATH: validate overlay and exit."""
    from poagent.board.overlay_validator import validate_overlay

    p = Path(path)
    if not p.exists():
        print(f"ERROR: overlay file not found: {path}", file=sys.stderr)
        return 1

    try:
        errors = validate_overlay(p)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: validation raised exception: {exc}", file=sys.stderr)
        return 1

    if errors:
        print(f"INVALID overlay ({len(errors)} error(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: overlay {path} is valid.")
    return 0


def _cmd_verify_report(path: str) -> int:
    """--verify-report PATH: verify HMAC-SHA-256 signature and exit."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: report file not found: {path}", file=sys.stderr)
        return 1

    content = p.read_text(encoding="utf-8")
    signing_key = os.environ.get("POAGENT_SIGNING_KEY", "")
    ok, msg = verify_report(content, signing_key=signing_key if signing_key else None)
    if ok:
        print(f"OK: signature valid — {msg}")
        return 0
    else:
        print(f"FAIL: {msg}", file=sys.stderr)
        return 1


def _cmd_dry_run(args: argparse.Namespace) -> int:
    """--dry-run: validate DTS + overlay, exit 0 or 5."""
    from poagent.board.dts_parser import parse_dts, parse_po_agent_properties
    from poagent.board.overlay_validator import validate_overlay, check_overlay_confirmation

    dts_path = args.dts
    overlay_path = args.overlay
    errors: list[str] = []

    # DTS validation
    if not dts_path:
        errors.append("--dts is required for --dry-run")
    else:
        p = Path(dts_path)
        if not p.exists():
            errors.append(f"DTS file not found: {dts_path}")
        else:
            try:
                tree = parse_dts(p)
                parse_po_agent_properties(tree)
                print(f"OK: DTS {dts_path} parsed successfully.")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"DTS parse error: {exc}")

    # Overlay validation
    if overlay_path:
        op = Path(overlay_path)
        if not op.exists():
            errors.append(f"Overlay file not found: {overlay_path}")
        else:
            try:
                overlay_errors = validate_overlay(op)
                if overlay_errors:
                    for e in overlay_errors:
                        errors.append(f"Overlay: {e}")
                else:
                    print(f"OK: overlay {overlay_path} is valid.")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Overlay error: {exc}")

    if errors:
        print("DRY-RUN FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return VERDICT_EXIT_CODES["DRY_RUN_FAIL"]

    print("DRY-RUN PASSED: DTS and overlay are valid.")
    return 0


def _cmd_batch(args: argparse.Namespace, api_key: str) -> int:
    """--batch --fleet-csv PATH: fleet mode."""
    from poagent.agents.batch_orchestrator import run_batch

    if not args.fleet_csv:
        print("ERROR: --fleet-csv is required with --batch", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    fleet_path = Path(args.fleet_csv)
    if not fleet_path.exists():
        print(f"ERROR: fleet CSV not found: {args.fleet_csv}", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _build_config(args)
    results = run_batch(
        fleet_csv=fleet_path,
        config=config,
        api_key=api_key,
        output_dir=output_dir,
        concurrency=args.fleet_concurrency,
    )

    # Print summary table
    print("\nFleet Summary:")
    print(f"{'Board':<30} {'Verdict':<15} {'Run ID'}")
    print("-" * 70)
    any_fail = False
    for r in results:
        print(f"{r.board_name:<30} {r.verdict:<15} {r.run_id}")
        if r.verdict in ("FAIL", "PREFLIGHT_FAIL", "INCOMPLETE"):
            any_fail = True

    return VERDICT_EXIT_CODES["FAIL"] if any_fail else VERDICT_EXIT_CODES["PASS"]


def _build_config(args: argparse.Namespace) -> PoAgentConfig:
    """Build PoAgentConfig from parsed CLI args."""
    # Parse host/port
    host = ""
    port = args.port
    ssh_user = getattr(args, "ssh_user", "root")

    if args.host:
        # Support user@host:port
        raw = args.host
        if "@" in raw:
            ssh_user, raw = raw.split("@", 1)
        if ":" in raw:
            host, port_str = raw.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                host = raw
        else:
            host = raw

    # Output dir
    output_dir = Path(args.output_dir)

    # Log dir
    log_dir = Path(args.log_dir) if getattr(args, "log_dir", None) else output_dir / "logs"

    # Spec page range
    spec_page_range: tuple[int, int] | None = None
    if getattr(args, "spec_page_range", None):
        spec_page_range = (args.spec_page_range[0], args.spec_page_range[1])

    return PoAgentConfig(
        # Connection
        host=host,
        port=port,
        ssh_user=ssh_user,
        ssh_key_file=getattr(args, "ssh_key", None) or "~/.ssh/id_rsa",
        serial_port=getattr(args, "serial", None) or "",
        serial_baud=getattr(args, "baud", 115200),
        # Board
        board_name=getattr(args, "board_name", None) or host or "unknown",
        overlay_confirm_mode=getattr(args, "confirm_overlay", "interactive"),
        # Run modes
        allow_destructive_tests=getattr(args, "allow_destructive_tests", False),
        unsafe_shutdown_mode=getattr(args, "unsafe_shutdown_mode", "ci_mode"),
        watchdog_keepalive=getattr(args, "watchdog_keepalive", "warn"),
        # LLM
        model=getattr(args, "model", "claude-sonnet-4-6"),
        agent_timeout_seconds=getattr(args, "agent_timeout", 120),
        # Resume
        force_resume=getattr(args, "force_resume", False),
        run_id=getattr(args, "resume", None) or "",
    )


def _cmd_reanalyze(args: argparse.Namespace, api_key: str) -> int:
    """--reanalyze: re-run triage from cached results."""
    if not args.resume:
        print("ERROR: --reanalyze requires --resume <run_id>", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    run_id = args.resume
    output_dir = Path(args.output_dir)
    run_dir = output_dir / run_id

    cache_file = run_dir / "phase2_cache.json"
    if not cache_file.exists():
        print(f"ERROR: no cached results found at {cache_file}", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    from poagent.agents.triage import run_triage_agent
    from poagent.agents.specialist import DomainResult, Finding
    from poagent.report.generator import generate_html_report, save_html_report, save_json_report

    with open(cache_file) as f:
        cache = json.load(f)

    # Reconstruct DomainResult list from cache
    all_results: dict[str, DomainResult] = {}
    for domain, data in cache.get("domain_results", {}).items():
        findings = [
            Finding(
                severity=fd["severity"],
                code=fd["code"],
                message=fd["message"],
                evidence=fd.get("evidence", {}),
                recommended_action=fd.get("recommended_action", ""),
            )
            for fd in data.get("findings", [])
        ]
        all_results[domain] = DomainResult(
            domain=domain,
            status=data["status"],
            summary=data["summary"],
            findings=findings,
            root_cause_hypothesis=data.get("root_cause_hypothesis", ""),
            confidence=data.get("confidence", 0.0),
            recommended_actions=data.get("recommended_actions", []),
            raw_data=data.get("raw_data", {}),
            iterations=data.get("iterations", 0),
            tools_called=data.get("tools_called", []),
            timed_out_probes=data.get("timed_out_probes", []),
            gate4_method5_only=data.get("gate4_method5_only", False),
            confidence_tags=data.get("confidence_tags", []),
        )

    boot_context = cache.get("boot_context", {})
    config = _build_config(args)

    triage = run_triage_agent(
        domain_results=list(all_results.values()),
        boot_context=boot_context,
        board_profile=None,
        config=config,
        api_key=api_key,
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    html = generate_html_report(triage_output=triage, boot_context=boot_context, run_id=run_id)

    if not args.json_only:
        html_path = save_html_report(html, str(run_dir), run_id)
        print(f"HTML report: {html_path}")

    json_path = save_json_report(triage, str(run_dir), run_id)
    print(f"JSON report: {json_path}")

    return VERDICT_EXIT_CODES.get(
        getattr(triage, "po_verdict", getattr(triage, "verdict", "INCOMPLETE")),
        VERDICT_EXIT_CODES["INCOMPLETE"],
    )


def _cmd_spec_ingest(args: argparse.Namespace, api_key: str, config: PoAgentConfig) -> None:
    """Ingest spec PDF/CSV before main analysis."""
    from poagent.board.spec_parser import ingest_spec

    page_range = None
    if args.spec_page_range:
        page_range = (args.spec_page_range[0], args.spec_page_range[1])

    if args.spec_pdf:
        print(f"Ingesting spec PDF: {args.spec_pdf}")
        result = ingest_spec(
            pdf_path=Path(args.spec_pdf),
            api_key=api_key,
            model=config.model,
            page_range=page_range,
        )
        log.info("spec_ingested", pages=result.get("pages_processed"), rails=len(result.get("rails", {})))

    if args.spec_csv:
        print(f"Ingesting spec CSV: {args.spec_csv}")
        # CSV parsing: simple key=value or header-row CSV for rail specs
        import csv as _csv
        csv_path = Path(args.spec_csv)
        if csv_path.exists():
            with open(csv_path) as f:
                reader = _csv.DictReader(f)
                rows = list(reader)
            log.info("spec_csv_loaded", rows=len(rows), path=str(csv_path))


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    # ── Utility sub-commands (no board connection needed) ────────────────────

    if args.validate_overlay:
        return _cmd_validate_overlay(args.validate_overlay)

    if args.verify_report:
        return _cmd_verify_report(args.verify_report)

    if args.dry_run:
        return _cmd_dry_run(args)

    # ── API key resolution ───────────────────────────────────────────────────
    api_key = resolve_api_key(config_value=getattr(args, "api_key", None))
    if not api_key:
        print(
            "ERROR: No Anthropic API key found. "
            "Set ANTHROPIC_API_KEY env, use --api-key, or store via keyring.",
            file=sys.stderr,
        )
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    # ── Batch mode ───────────────────────────────────────────────────────────
    if args.batch:
        return _cmd_batch(args, api_key)

    # ── Reanalyze mode ───────────────────────────────────────────────────────
    if args.reanalyze:
        return _cmd_reanalyze(args, api_key)

    # ── Normal single-board run ──────────────────────────────────────────────

    # Validate connection args
    if not args.host and not args.serial:
        print("ERROR: --host or --serial is required.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    if not args.dts:
        print("ERROR: --dts is required.", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    if not Path(args.dts).exists():
        print(f"ERROR: DTS file not found: {args.dts}", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    # Subsystem validation [LAST-S5]
    from poagent.board.clock_topology import KNOWN_DOMAINS

    if args.subsystems:
        unknown = set(args.subsystems) - KNOWN_DOMAINS
        if unknown:
            print(
                f"ERROR: Unknown subsystem(s): {', '.join(sorted(unknown))}. "
                f"Valid: {', '.join(sorted(KNOWN_DOMAINS))}",
                file=sys.stderr,
            )
            return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    # Run ID — timestamp + short UUID suffix for uniqueness
    _ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _short = str(uuid.uuid4())[:8]
    run_id = getattr(args, "run_id", None) or f"{_ts}_{_short}"

    # Build output dir
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config = _build_config(args)

    # Parse board profile from DTS
    from poagent.board.dts_parser import parse_dts
    from poagent.board.overlay_validator import validate_overlay, check_overlay_confirmation
    from poagent.board.board_profile import BoardProfile

    # Overlay validation (if provided)
    if args.overlay:
        overlay_path = Path(args.overlay)
        if not overlay_path.exists():
            print(f"ERROR: Overlay file not found: {args.overlay}", file=sys.stderr)
            return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

        overlay_report = validate_overlay(str(overlay_path))
        if overlay_report.errors:
            print(f"ERROR: Invalid overlay ({len(overlay_report.errors)} error(s)):", file=sys.stderr)
            for e in overlay_report.errors:
                print(f"  - {e}", file=sys.stderr)
            return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

        confirmed, confirm_msg = check_overlay_confirmation(
            overlay_path=overlay_path,
            mode=args.confirm_overlay,
        )
        if not confirmed:
            print(f"ERROR: Overlay confirmation failed: {confirm_msg}", file=sys.stderr)
            return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    try:
        board_profile = parse_dts(
            args.dts,
            overlay_path=args.overlay or None,
            board_name=config.board_name,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: DTS parse failed: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    # Spec ingestion (pre-run, best-effort)
    if args.spec_pdf or args.spec_csv:
        try:
            _cmd_spec_ingest(args, api_key, config)
        except Exception as exc:  # noqa: BLE001
            log.warning("spec_ingest_failed", error=str(exc))

    # Build runner
    from poagent.probes.base import ProbeRunner

    try:
        if args.serial:
            runner = ProbeRunner(
                ssh_semaphore=config._ssh_semaphore,
                pause_event=config._pause_event,
                abort_event=config._abort_event,
                board_ip=config.host,
                board_name=config.board_name,
                run_id=run_id,
            ).via_serial(
                port=args.serial,
                baud=args.baud,
            )
        else:
            runner = ProbeRunner(
                ssh_semaphore=config._ssh_semaphore,
                pause_event=config._pause_event,
                abort_event=config._abort_event,
                board_ip=config.host,
                board_name=config.board_name,
                run_id=run_id,
            ).via_ssh(
                host=config.host,
                port=config.port,
                user=config.ssh_user,
                key_file=config.ssh_key_file or None,
                password=os.environ.get("POAGENT_SSH_PASSWORD") or None,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Connection failed: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["PREFLIGHT_FAIL"]

    # Run orchestrator
    from poagent.agents.orchestrator import run_orchestrator

    print(f"Starting PoAgent run {run_id} on {args.host or args.serial}")
    print(f"Output directory: {run_dir}")

    try:
        result = run_orchestrator(
            config=config,
            board_profile=board_profile,
            runner=runner,
            api_key=api_key,
            run_id=run_id,
            output_dir=run_dir,
            dry_run=False,
            subsystems=args.subsystems or None,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]
    except Exception as exc:  # noqa: BLE001
        log.error("orchestrator_fatal", error=str(exc), exc_info=True)
        print(f"ERROR: Orchestrator failed: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]
    finally:
        try:
            runner.close()
        except Exception:  # noqa: BLE001
            pass

    # Print verdict
    verdict = getattr(result, "verdict", getattr(result, "po_verdict", "INCOMPLETE"))
    print(f"\nVerdict: {verdict}")
    if result.html_report_path:
        print(f"  HTML: {result.html_report_path}")
    if result.json_report_path:
        print(f"  JSON: {result.json_report_path}")

    return VERDICT_EXIT_CODES.get(verdict, VERDICT_EXIT_CODES["INCOMPLETE"])


if __name__ == "__main__":
    sys.exit(main())
