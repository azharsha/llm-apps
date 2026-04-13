"""Batch / fleet mode orchestration [§16].

Reads a fleet CSV and runs PoAgent on each board in parallel up to
`concurrency` boards at a time. Each board gets its own run_id,
output directory, and ProbeRunner. Results are collected into a
FleetResult list returned to the caller.

CSV schema (required columns):
    board_name, host, dts, overlay (optional), board_name (optional)

Optional columns:
    ssh_user, ssh_key, port, serial, baud, subsystems (comma-separated)

[§16] Fleet mode contract:
  - Board failures do not abort other boards.
  - Each board run is independent (separate board lock, separate log).
  - Summary CSV written to output_dir/fleet_summary.csv.
  - If any board returns FAIL/INCOMPLETE/PREFLIGHT_FAIL → overall exit 1.
"""

from __future__ import annotations

import csv
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from poagent.config import PoAgentConfig

log = structlog.get_logger(__name__)


@dataclass
class BoardRunResult:
    """Result for a single board in fleet mode."""
    board_name: str
    run_id: str
    verdict: str
    html_report: str = ""
    json_report: str = ""
    error: str = ""
    elapsed_s: float = 0.0


@dataclass
class FleetSummary:
    """Aggregate fleet run results."""
    results: list[BoardRunResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    conditional: int = 0
    incomplete: int = 0

    def compute(self) -> None:
        self.total = len(self.results)
        for r in self.results:
            if r.verdict == "PASS":
                self.passed += 1
            elif r.verdict == "FAIL":
                self.failed += 1
            elif r.verdict == "CONDITIONAL":
                self.conditional += 1
            else:
                self.incomplete += 1


def _read_fleet_csv(csv_path: Path) -> list[dict[str, str]]:
    """Parse fleet CSV into list of board config dicts.

    Required columns: host OR serial, dts
    Optional: board_name, ssh_user, ssh_key, port, baud, overlay, subsystems
    """
    required = {"dts"}
    rows: list[dict[str, str]] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Fleet CSV {csv_path} has no headers")

        headers = set(reader.fieldnames)
        if not required.issubset(headers):
            missing = required - headers
            raise ValueError(f"Fleet CSV missing required columns: {missing}")

        if "host" not in headers and "serial" not in headers:
            raise ValueError("Fleet CSV must have 'host' or 'serial' column")

        for i, row in enumerate(reader, start=2):
            host = row.get("host", "").strip()
            serial = row.get("serial", "").strip()
            if not host and not serial:
                log.warning("fleet_csv_row_no_connection", row=i)
                continue
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"Fleet CSV {csv_path} contains no valid board rows")

    return rows


def _run_board(
    row: dict[str, str],
    config: PoAgentConfig,
    api_key: str,
    output_dir: Path,
    results: list[BoardRunResult],
    lock: threading.Lock,
) -> None:
    """Run PoAgent on a single board row. Appends BoardRunResult to results."""
    from poagent.board.dts_parser import parse_dts, parse_po_agent_properties
    from poagent.board.board_profile import BoardProfile
    from poagent.board.overlay_validator import validate_overlay
    from poagent.probes.base import ProbeRunner
    from poagent.agents.orchestrator import run_orchestrator

    host = row.get("host", "").strip()
    serial = row.get("serial", "").strip()
    board_name = row.get("board_name", host or serial or "unknown").strip()
    run_id = str(uuid.uuid4())
    run_dir = output_dir / f"{board_name}_{run_id[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    log.info("fleet_board_start", board=board_name, host=host or serial, run_id=run_id)

    def _fail(msg: str) -> BoardRunResult:
        elapsed = time.monotonic() - start
        log.error("fleet_board_error", board=board_name, error=msg)
        return BoardRunResult(
            board_name=board_name,
            run_id=run_id,
            verdict="PREFLIGHT_FAIL",
            error=msg,
            elapsed_s=round(elapsed, 1),
        )

    # DTS
    dts_path = Path(row.get("dts", ""))
    if not dts_path.exists():
        r = _fail(f"DTS not found: {dts_path}")
        with lock:
            results.append(r)
        return

    try:
        dts_tree = parse_dts(dts_path)
        board_props = parse_po_agent_properties(dts_tree)
    except Exception as exc:  # noqa: BLE001
        r = _fail(f"DTS parse failed: {exc}")
        with lock:
            results.append(r)
        return

    # Overlay
    overlay_data: dict = {}
    overlay_str = row.get("overlay", "").strip()
    if overlay_str:
        op = Path(overlay_str)
        if op.exists():
            import json as _json
            import yaml as _yaml
            text = op.read_text()
            try:
                overlay_data = _json.loads(text)
            except ValueError:
                overlay_data = _yaml.safe_load(text) or {}

    try:
        board_profile = BoardProfile.from_dts_props(board_props, overlay=overlay_data)
    except Exception as exc:  # noqa: BLE001
        r = _fail(f"Board profile failed: {exc}")
        with lock:
            results.append(r)
        return

    # Override config fields for this board
    import dataclasses
    board_config = dataclasses.replace(
        config,
        host=host,
        port=int(row.get("port", config.port)),
        ssh_user=row.get("ssh_user", config.ssh_user),
        ssh_key_path=row.get("ssh_key", config.ssh_key_path),
        serial_device=serial,
        baud_rate=int(row.get("baud", config.baud_rate)),
        board_name=board_name,
        dts_path=str(dts_path),
        overlay_path=overlay_str,
    )

    # Subsystems
    subsystems_str = row.get("subsystems", "").strip()
    subsystems = [s.strip() for s in subsystems_str.split(",") if s.strip()] if subsystems_str else None

    # Runner
    try:
        if serial:
            runner = ProbeRunner.from_serial(
                device=serial,
                baud=board_config.baud_rate,
                config=board_config,
            )
        else:
            runner = ProbeRunner.from_ssh(
                host=host,
                port=board_config.port,
                user=board_config.ssh_user,
                key_path=board_config.ssh_key_path or None,
                password=board_config.ssh_password or None,
                config=board_config,
            )
    except Exception as exc:  # noqa: BLE001
        r = _fail(f"Connection failed: {exc}")
        with lock:
            results.append(r)
        return

    try:
        orch_result = run_orchestrator(
            config=board_config,
            board_profile=board_profile,
            runner=runner,
            api_key=api_key,
            run_id=run_id,
            output_dir=run_dir,
            dry_run=False,
            subsystems=subsystems,
        )
        verdict = getattr(orch_result, "po_verdict", "INCOMPLETE")
        html_report = str(run_dir / "report.html")
        json_report = str(run_dir / "report.json")
    except Exception as exc:  # noqa: BLE001
        log.error("fleet_board_orchestrator_error", board=board_name, error=str(exc), exc_info=True)
        verdict = "INCOMPLETE"
        html_report = ""
        json_report = ""
    finally:
        try:
            runner.close()
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.monotonic() - start
    br = BoardRunResult(
        board_name=board_name,
        run_id=run_id,
        verdict=verdict,
        html_report=html_report,
        json_report=json_report,
        elapsed_s=round(elapsed, 1),
    )
    log.info("fleet_board_done", board=board_name, verdict=verdict, elapsed_s=br.elapsed_s)

    with lock:
        results.append(br)


def _write_fleet_summary_csv(summary: FleetSummary, output_dir: Path) -> Path:
    """Write fleet_summary.csv to output_dir."""
    csv_path = output_dir / "fleet_summary.csv"
    fields = ["board_name", "run_id", "verdict", "elapsed_s", "html_report", "json_report", "error"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in summary.results:
            writer.writerow({
                "board_name": r.board_name,
                "run_id": r.run_id,
                "verdict": r.verdict,
                "elapsed_s": r.elapsed_s,
                "html_report": r.html_report,
                "json_report": r.json_report,
                "error": r.error,
            })

    log.info("fleet_summary_csv_written", path=str(csv_path))
    return csv_path


def run_batch(
    fleet_csv: Path,
    config: PoAgentConfig,
    api_key: str,
    output_dir: Path,
    concurrency: int = 4,
) -> list[BoardRunResult]:
    """Run PoAgent on all boards in fleet_csv.

    Boards run in parallel up to `concurrency` at a time.
    Returns list of BoardRunResult sorted by board_name.
    Writes fleet_summary.csv to output_dir.
    """
    rows = _read_fleet_csv(fleet_csv)
    log.info("fleet_start", boards=len(rows), concurrency=concurrency)

    results: list[BoardRunResult] = []
    results_lock = threading.Lock()

    # Thread pool via semaphore
    semaphore = threading.Semaphore(concurrency)

    def _worker(row: dict[str, str]) -> None:
        with semaphore:
            _run_board(
                row=row,
                config=config,
                api_key=api_key,
                output_dir=output_dir,
                results=results,
                lock=results_lock,
            )

    threads = [
        threading.Thread(target=_worker, args=(row,), daemon=True, name=f"board-{row.get('board_name', i)}")
        for i, row in enumerate(rows)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    results.sort(key=lambda r: r.board_name)

    summary = FleetSummary(results=results)
    summary.compute()

    log.info(
        "fleet_complete",
        total=summary.total,
        passed=summary.passed,
        failed=summary.failed,
        conditional=summary.conditional,
        incomplete=summary.incomplete,
    )

    _write_fleet_summary_csv(summary, output_dir)
    return results
