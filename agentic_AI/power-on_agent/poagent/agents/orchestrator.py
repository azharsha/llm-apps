"""PoAgent Orchestrator — full pipeline from Phase 0 to report output.

[PRD §4.1] Pipeline:
  Phase 0: boot_context capture (IRQ storm, panic scan, EDAC t0, clock map,
           silicon stepping, watchdog state, AER baseline)
  Gate 1-6: pre-flight checks
  Rail Sanity Barrier: critical rails (Python-only, no LLM)
  Phase 1: Power & Clocking → Compute & Memory (sequential LLM agents)
  Clock Cascade Resolver (pass 1)
  Phase 2: 8 domain agents in parallel (ThermalMonitorThread active)
  Clock Cascade Resolver (pass 2)
  EDAC delta t1
  Triage Agent
  Report generation + HMAC signing

[N-CG-03] pause_event.wait() BEFORE semaphore.acquire() everywhere.
[H-05] ThermalMonitorThread uses separate SSH connection outside semaphore pool.
[LAST-C1] watchdog_keepalive=auto lowers max_concurrent_ssh to 2.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from poagent.agents.board_lock import acquire_board_lock, BoardLockError
from poagent.agents.cascade_resolver import (
    resolve_clock_cascades,
    enrich_clock_map_from_debugfs,
)
from poagent.agents.edac_tracker import read_edac_counts, compute_ecc_delta
from poagent.agents.irq_storm import check_irq_storm, format_irq_storm_context
from poagent.agents.preflight import run_preflight, PreFlightError
from poagent.agents.rail_barrier import run_rail_barrier
from poagent.agents.specialist import run_domain_agent, DomainResult
from poagent.agents.thermal_monitor import make_thermal_monitor
from poagent.agents.triage import run_triage_agent, compute_po_verdict
from poagent.agents.watchdog_keepalive import (
    check_watchdog_state,
    handle_watchdog_conflict,
)
from poagent.board.clock_topology import (
    get_clock_topology,
    validate_clock_topology_consumers,
)
from poagent.board.stepping_reader import read_silicon_stepping
from poagent.codes import (
    SILICON_STEPPING_UNRESOLVED,
    CLOCK_TOPOLOGY_UNKNOWN,
    CLOCK_TOPOLOGY_CONSUMER_UNKNOWN,
    PANIC_DETECTED_WARNING,
    OOM_KILL_IN_DMESG,
    OOM_KILL_KERNEL_THREAD,
)
from poagent.probes.base import ProbeRunner
from poagent.report.generator import (
    generate_html_report,
    save_html_report,
    save_json_report,
)
from poagent.security.audit_log import BoardCommandLog
from poagent.security.log_rotator import rotate_logs
from poagent.security.signing import sign_report, verify_report

log = structlog.get_logger(__name__)

# Phase 2 execution order (all run in parallel)
PHASE2_DOMAINS = [
    "storage",
    "highspeed_serial",
    "display_graphics",
    "networking",
    "audio",
    "lowspeed_interface",
    "security_crypto",
    "sensors_misc",
]

PHASE1_DOMAINS = ["power_clocking", "compute_memory"]

# Verdict → exit code [FINAL-H1]
VERDICT_EXIT_CODES = {
    "PASS": 0,
    "FAIL": 1,
    "CONDITIONAL": 2,
    "INCOMPLETE": 3,
}


@dataclass
class OrchestratorResult:
    """Full result of the orchestrator pipeline."""
    verdict: str
    verdict_reason: str
    run_id: str
    html_report_path: str = ""
    json_report_path: str = ""
    exit_code: int = 3
    preflight_failed: bool = False
    barrier_failed: bool = False
    dry_run: bool = False
    dry_run_errors: list[str] = field(default_factory=list)


def _capture_boot_context(
    runner: ProbeRunner,
    config: object,
    board_profile: object,
    preflight_report: object,
) -> dict:
    """Capture Phase 0 boot context: kernel, uname, IRQ storm, panic scan, EDAC t0, etc."""
    boot_context: dict = {}

    # Kernel version
    result = runner.exec("cat /proc/version 2>/dev/null", timeout=5.0,
                         probe_name="boot_context_version")
    boot_context["kernel_version_raw"] = result.stdout.strip()
    m = re.search(r"Linux version (\S+)", result.stdout)
    boot_context["kernel_version"] = m.group(1) if m else "unknown"

    # uname
    result = runner.exec("uname -a 2>/dev/null", timeout=5.0, probe_name="boot_context_uname")
    boot_context["uname"] = result.stdout.strip()

    # OS release
    result = runner.exec("cat /etc/os-release 2>/dev/null", timeout=5.0,
                         probe_name="boot_context_osrelease")
    boot_context["os_release"] = result.stdout.strip()

    # IRQ storm check [CG-05]
    irq_storms = check_irq_storm(runner, config)
    boot_context.update(format_irq_storm_context(irq_storms))

    # dmesg_supports_k capability check [FINAL-C4]
    cap = runner.exec(
        r"dmesg --help 2>&1 | grep -c '\-k' || echo 0",
        timeout=3.0, probe_name="boot_context_dmesg_k"
    )
    boot_context["dmesg_supports_k"] = cap.stdout.strip() not in ("", "0")

    # Kernel panic / BUG scan [N-SG-04, R-01]
    boot_context["kernel_panics_this_boot"] = _scan_kernel_panics(runner, boot_context, config)

    # EDAC snapshot t0 [CG-06]
    edac_t0 = read_edac_counts(runner)
    boot_context["edac_snapshot_t0"] = {
        "ce": edac_t0.ce, "ue": edac_t0.ue, "source": edac_t0.source
    }
    boot_context["edac_source"] = edac_t0.source

    # Silicon stepping [FINAL-S6]
    stepping = read_silicon_stepping(runner, board_profile)
    boot_context["silicon_stepping"] = stepping
    if stepping.get("source") == "fallback":
        log.warning(SILICON_STEPPING_UNRESOLVED,
                    platform=stepping.get("platform"),
                    raw=stepping.get("raw"))

    # Watchdog state [FINAL-S1]
    boot_context["watchdog_state"] = check_watchdog_state(runner, config)

    # Gate 4 method5 info
    boot_context["gate4_method5_only"] = getattr(preflight_report, "gate4_method5_only", False)
    boot_context["debugfs_available"] = getattr(preflight_report, "debugfs_available", True)
    boot_context["dts_kernel_version_mismatch"] = getattr(
        preflight_report, "dts_version_mismatch", None
    )

    # AER baseline [O-04]
    aer_baseline = _read_aer_baseline(runner)
    boot_context["aer_baseline"] = aer_baseline

    log.info("boot_context_captured",
             kernel=boot_context["kernel_version"],
             panics=len(boot_context["kernel_panics_this_boot"]),
             irq_storm=boot_context["irq_storm"] is not None,
             edac_source=edac_t0.source)

    return boot_context


def _scan_kernel_panics(runner: ProbeRunner, boot_context: dict, config: object) -> list[dict]:
    """[N-SG-04, R-01, FINAL-C4] Scan dmesg for kernel panic / BUG / OOM."""
    supports_k = boot_context.get("dmesg_supports_k", True)
    if supports_k:
        dmesg_cmd = r"dmesg -k --notime 2>/dev/null"
    else:
        dmesg_cmd = (
            r"dmesg 2>/dev/null | grep -v '^\[.*\] rc\.' | grep -v 'systemd\[1\]'"
        )

    grep_pattern = (
        r"'Kernel panic|BUG:|general protection fault|WARN_ON|Out of memory: Killed process'"
    )
    result = runner.exec(
        f"{dmesg_cmd} | grep -E {grep_pattern}",
        timeout=5.0, probe_name="boot_context_panic_scan"
    )
    matches = _parse_panic_lines(result.stdout, "dmesg")

    # kern.log fallback [R-01]
    if getattr(config, "kern_log_fallback", True):
        kern_result = runner.exec(
            r"[ -f /var/log/kern.log ] && "
            r"grep -E 'Kernel panic|BUG:' /var/log/kern.log | tail -20 || true",
            timeout=5.0, probe_name="boot_context_kernlog"
        )
        matches += _parse_panic_lines(kern_result.stdout, "kern.log")

    return matches


def _parse_panic_lines(output: str, source: str) -> list[dict]:
    results = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        pattern = "unknown"
        if "Kernel panic" in line:
            pattern = "panic"
        elif "BUG:" in line:
            pattern = "bug"
        elif "general protection fault" in line:
            pattern = "gpf"
        elif "WARN_ON" in line:
            pattern = "warn_on"
        elif "Out of memory: Killed" in line:
            pattern = "oom"
        results.append({"line": line, "pattern": pattern, "source": source})
    return results


def _read_aer_baseline(runner: ProbeRunner) -> dict:
    """[O-04] Read PCIe AER correctable error baseline before Phase 2."""
    try:
        result = runner.exec(
            "find /sys/bus/pci/devices -name 'aer_dev_correctable' 2>/dev/null | head -20",
            timeout=5.0, probe_name="aer_baseline_find"
        )
        baseline = {}
        for path in result.stdout.splitlines():
            path = path.strip()
            if not path:
                continue
            val_result = runner.exec(f"cat {path} 2>/dev/null", timeout=2.0,
                                     probe_name="aer_baseline_read")
            # Parse the key-value output from aer_dev_correctable
            for line in val_result.stdout.splitlines():
                if " " in line:
                    parts = line.split()
                    if len(parts) == 2:
                        baseline[f"{path}:{parts[0]}"] = int(parts[1]) if parts[1].isdigit() else 0
        return baseline
    except Exception as exc:
        log.debug("aer_baseline_failed", error=str(exc))
        return {}


def _tag_panic_confidence(
    domain_results: dict[str, DomainResult],
    boot_context: dict,
) -> None:
    """[N-SG-04] Tag all domain results LOW_CONFIDENCE_PANIC_DETECTED if panic found."""
    panics = boot_context.get("kernel_panics_this_boot", [])
    if not panics:
        return
    for result in domain_results.values():
        result.confidence_tags.append("LOW_CONFIDENCE_PANIC_DETECTED")
        result.confidence = min(result.confidence, 0.4)


def _classify_oom_kills(
    domain_results: dict[str, DomainResult],
    boot_context: dict,
) -> None:
    """[LAST-C2] Classify OOM kill severity in boot_context."""
    oom_events = [
        p for p in boot_context.get("kernel_panics_this_boot", [])
        if p.get("pattern") == "oom"
    ]
    if not oom_events:
        return

    for event in oom_events:
        line = event.get("line", "")
        if "memtester" in line.lower():
            # Check if MEMTESTER_SKIPPED_LOW_MEMORY was already set
            memtester_skipped = any(
                "MEMTESTER_SKIPPED_LOW_MEMORY" in str(f)
                for r in domain_results.values()
                for f in r.findings
            )
            if memtester_skipped:
                log.warning(OOM_KILL_IN_DMESG,
                            severity="WARNING",
                            msg="memtester OOM kill, MEMTESTER_SKIPPED_LOW_MEMORY present — probe over-allocated")
            else:
                log.warning(OOM_KILL_IN_DMESG,
                            severity="CONDITIONAL",
                            msg="memtester OOM kill without skip — platform memory deficiency suspected")
        elif re.search(r'kworker|kswapd|kthreadd', line):
            log.error(OOM_KILL_KERNEL_THREAD,
                      severity="FAIL",
                      msg="Kernel thread OOM kill — memory corruption or severe reclaim failure")
            # Upgrade verdict
            for r in domain_results.values():
                if r.domain == "compute_memory":
                    r.confidence_tags.append("OOM_KILL_KERNEL_THREAD")
        else:
            log.warning(OOM_KILL_IN_DMESG,
                        severity="CONDITIONAL",
                        msg="Unexpected userspace process OOM killed")


def run_orchestrator(
    config: object,
    board_profile: object,
    runner: ProbeRunner,
    api_key: str,
    run_id: str,
    output_dir: str,
    dry_run: bool = False,
    subsystems: Optional[list[str]] = None,
) -> OrchestratorResult:
    """Run the full PoAgent diagnostic pipeline.

    Args:
        config: PoAgentConfig instance
        board_profile: BoardProfile from DTS parse
        runner: ProbeRunner connected to target board
        api_key: Anthropic API key
        run_id: Unique run identifier
        output_dir: Directory for run logs and reports
        dry_run: If True, validate DTS/overlay only (no board probing)
        subsystems: If set, only run specified domain(s)

    Returns:
        OrchestratorResult with verdict and report paths.
    """
    board_name = getattr(config, "board_name", "") or getattr(board_profile, "board_name", "unknown")
    board_ip = getattr(config, "board_ip", "")

    log.info("orchestrator_start", run_id=run_id, board=board_name, dry_run=dry_run)

    # ── Log rotation [FINAL-H2] ────────────────────────────────────────────
    log_root = getattr(config, "log_root", os.path.expanduser("~/.poagent/logs"))
    rotate_logs(
        log_root=log_root,
        retention_days=getattr(config, "log_retention_days", 30),
        max_total_mb=getattr(config, "log_max_total_mb", 500),
        size_rotation_exempt=getattr(config, "log_size_rotation_exempt", False),
        active_atime_window_s=getattr(config, "log_active_atime_window_s", 3600),
        current_run_dir=output_dir,
    )

    # ── Board lock [R-02] ──────────────────────────────────────────────────
    max_run_time = getattr(config, "agent_timeout_seconds", 120) * 12 + 600
    try:
        board_lock = acquire_board_lock(
            board_name=board_name,
            max_run_time_s=max_run_time,
            run_id=run_id,
            lock_dir=getattr(config, "lock_dir", "/var/lock/poagent"),
        )
    except BoardLockError as exc:
        log.error("board_lock_failed", error=str(exc))
        return OrchestratorResult(
            verdict="INCOMPLETE",
            verdict_reason=str(exc),
            run_id=run_id,
            exit_code=3,
        )

    # ── Audit log ──────────────────────────────────────────────────────────
    audit_log = BoardCommandLog(
        run_dir=output_dir,
        run_id=run_id,
        board_name=board_name,
    )

    # Attach audit log to runner
    runner._audit_log = audit_log  # type: ignore[attr-defined]
    runner._run_id = run_id  # type: ignore[attr-defined]
    runner._board_name = board_name  # type: ignore[attr-defined]

    # ── Events ────────────────────────────────────────────────────────────
    pause_event = threading.Event()
    abort_event = threading.Event()
    config._pause_event = pause_event  # type: ignore[attr-defined]
    config._abort_event = abort_event  # type: ignore[attr-defined]

    # SSH semaphore [H-05, LAST-C1]
    max_ssh = getattr(config, "max_concurrent_ssh", 3)
    watchdog_mode = getattr(config, "watchdog_keepalive", "warn")
    if watchdog_mode == "auto":
        max_ssh = min(max_ssh, 2)
        log.info("ssh_semaphore_lowered_for_watchdog", max_concurrent_ssh=max_ssh)
    ssh_semaphore = threading.Semaphore(max_ssh)
    config._ssh_semaphore = ssh_semaphore  # type: ignore[attr-defined]
    runner._ssh_semaphore = ssh_semaphore  # type: ignore[attr-defined]

    try:
        return _run_pipeline(
            config=config,
            board_profile=board_profile,
            runner=runner,
            api_key=api_key,
            run_id=run_id,
            output_dir=output_dir,
            dry_run=dry_run,
            subsystems=subsystems,
            audit_log=audit_log,
            pause_event=pause_event,
            abort_event=abort_event,
            ssh_semaphore=ssh_semaphore,
            board_lock=board_lock,
            board_name=board_name,
            board_ip=board_ip,
        )
    finally:
        audit_log.close()
        board_lock.release()
        runner.close()


def _run_pipeline(
    config, board_profile, runner, api_key, run_id, output_dir,
    dry_run, subsystems, audit_log, pause_event, abort_event,
    ssh_semaphore, board_lock, board_name, board_ip,
) -> OrchestratorResult:
    """Inner pipeline. Called by run_orchestrator after setup."""

    # ── Clock dependency map [CG-04] ───────────────────────────────────────
    clock_dep_map: dict = getattr(board_profile, "clock_dependency_map", {}) or {}

    # Augment with platform topology DB [U-02]
    soc_compat = getattr(board_profile, "soc_compatible", "")
    topo_db = get_clock_topology(soc_compat)
    if topo_db is None:
        log.warning(CLOCK_TOPOLOGY_UNKNOWN, soc=soc_compat)
    else:
        # Merge platform DB into clock_dep_map (DTS phandles take precedence)
        for clk_name, entry in topo_db.clocks.items():
            if clk_name not in clock_dep_map:
                clock_dep_map[clk_name] = {
                    "parent": entry.parent,
                    "consumers": list(entry.consumers),
                }

    # [LAST-S5] Validate consumer domain names
    topology_warnings = validate_clock_topology_consumers(clock_dep_map)
    for w in topology_warnings:
        log.warning(CLOCK_TOPOLOGY_CONSUMER_UNKNOWN, msg=w)

    # ── Dry run ────────────────────────────────────────────────────────────
    if dry_run:
        return _run_dry_run(
            config=config, board_profile=board_profile,
            clock_dep_map=clock_dep_map, topology_warnings=topology_warnings,
            run_id=run_id, output_dir=output_dir,
        )

    # ── Pre-flight gates ───────────────────────────────────────────────────
    preflight_report = None
    try:
        preflight_report = run_preflight(runner, config, board_profile)
    except PreFlightError as exc:
        log.error("preflight_failed", error=str(exc))
        return OrchestratorResult(
            verdict="INCOMPLETE",
            verdict_reason=f"Pre-flight gate failure: {exc}",
            run_id=run_id,
            exit_code=4,  # PREFLIGHT_FAIL [FINAL-H1]
            preflight_failed=True,
        )

    debugfs_available = preflight_report.debugfs_available
    enum_failures = preflight_report.enum_failures
    gate4_method5_only = preflight_report.gate4_method5_only

    # ── Boot context capture (Phase 0) ────────────────────────────────────
    boot_context = _capture_boot_context(runner, config, board_profile, preflight_report)

    # Augment clock map from debugfs [CG-04 Source 2]
    if debugfs_available:
        clock_dep_map = enrich_clock_map_from_debugfs(runner, clock_dep_map, True)

    # Store clock map in boot context
    boot_context["clock_dependency_map"] = clock_dep_map

    # ── Watchdog conflict handling [FINAL-S1] ──────────────────────────────
    wdt_state = boot_context.get("watchdog_state", {})
    wdt_thread = None
    if wdt_state.get("conflict"):
        try:
            # Create a dedicated runner for watchdog keepalive
            wdt_runner = ProbeRunner(
                domain="watchdog_keepalive",
                board_ip=board_ip,
                pause_event=pause_event,
                abort_event=abort_event,
                ssh_semaphore=threading.Semaphore(1),
            )
            wdt_runner.via_ssh(
                host=board_ip,
                user=getattr(config, "ssh_user", "root"),
                key_file=getattr(config, "ssh_key_file", None),
                password=getattr(config, "ssh_password", None),
            )
            wdt_thread = handle_watchdog_conflict(wdt_runner, config, wdt_state, abort_event)
        except RuntimeError as exc:
            log.error("watchdog_conflict_abort", error=str(exc))
            return OrchestratorResult(
                verdict="INCOMPLETE",
                verdict_reason=str(exc),
                run_id=run_id,
                exit_code=4,
                preflight_failed=True,
            )

    # ── Rail Sanity Barrier [CG-01] ────────────────────────────────────────
    barrier_report = run_rail_barrier(runner, board_profile, config)
    if barrier_report.is_fail:
        # Rail sanity failed — skip agents, go directly to triage
        log.error("barrier_failed", failed_rails=barrier_report.failed_rails)
        triage = run_triage_agent(
            domain_results={},
            boot_context=boot_context,
            config=config,
            api_key=api_key,
            run_id=run_id,
            board_name=board_name,
            preflight_report=preflight_report,
            barrier_failed=True,
        )
        return _finalize_report(
            triage=triage, boot_context=boot_context,
            preflight_report=preflight_report, run_id=run_id,
            output_dir=output_dir, config=config,
            barrier_failed=True,
        )

    # ── Phase 1: Sequential LLM agents ────────────────────────────────────
    phase1_results: dict[str, DomainResult] = {}
    phase1_domains = subsystems or PHASE1_DOMAINS

    for domain in phase1_domains:
        if domain not in PHASE1_DOMAINS:
            continue
        if abort_event.is_set():
            break
        result = run_domain_agent(
            domain=domain,
            runner=runner,
            board_profile=board_profile,
            boot_context=boot_context,
            config=config,
            api_key=api_key,
            enum_failures=enum_failures,
            debugfs_available=debugfs_available,
            gate4_method5_only=gate4_method5_only,
        )
        phase1_results[domain] = result
        # Cache domain result
        _cache_domain_result(result, output_dir, run_id)

    # ── Clock Cascade Resolver — Pass 1 ───────────────────────────────────
    if "power_clocking" in phase1_results:
        phase1_results = resolve_clock_cascades(
            phase1_result=phase1_results["power_clocking"],
            phase2_results=phase1_results,
            clock_dependency_map=clock_dep_map,
        )

    # ── Phase 2: Parallel LLM agents + ThermalMonitorThread ───────────────
    phase2_results: dict[str, DomainResult] = {}
    phase2_domains = subsystems or PHASE2_DOMAINS
    phase2_domains = [d for d in phase2_domains if d in PHASE2_DOMAINS]
    phase2_start_time = time.time()

    # Spawn ThermalMonitorThread [SG-01, H-05]
    thermal_monitor = make_thermal_monitor(
        board_ip=board_ip,
        config=config,
        pause_event=pause_event,
        abort_event=abort_event,
        ssh_semaphore=ssh_semaphore,
    )
    if thermal_monitor.available:
        thermal_monitor.start()

    # Run Phase 2 domains in parallel via threads
    def _run_domain_thread(domain: str) -> None:
        result = run_domain_agent(
            domain=domain,
            runner=runner,
            board_profile=board_profile,
            boot_context=boot_context,
            config=config,
            api_key=api_key,
            enum_failures=enum_failures,
            debugfs_available=debugfs_available,
            gate4_method5_only=gate4_method5_only,
        )
        phase2_results[domain] = result
        _cache_domain_result(result, output_dir, run_id)

    threads: list[threading.Thread] = []
    for domain in phase2_domains:
        if abort_event.is_set():
            break
        t = threading.Thread(target=_run_domain_thread, args=(domain,), name=f"agent_{domain}")
        t.start()
        threads.append(t)

    for t in threads:
        agent_timeout = getattr(config, "agent_timeout_seconds", 120)
        t.join(timeout=agent_timeout + 30)

    # Stop thermal monitor
    thermal_monitor.stop()
    if thermal_monitor.available:
        thermal_monitor.join(timeout=10)

    # Stop watchdog keepalive
    if wdt_thread is not None:
        wdt_thread.stop()
        wdt_thread.join(timeout=5)

    # ── EDAC delta t1 [CG-06] ─────────────────────────────────────────────
    edac_t1 = read_edac_counts(runner)
    edac_t0_snap = boot_context.get("edac_snapshot_t0", {})
    # Reconstruct t0 snapshot
    from poagent.agents.edac_tracker import EccSnapshot
    edac_t0_obj = EccSnapshot(
        ce=edac_t0_snap.get("ce"),
        ue=edac_t0_snap.get("ue"),
        source=edac_t0_snap.get("source", "unavailable"),
    )
    phase2_window_min = (time.time() - phase2_start_time) / 60
    edac_delta = compute_ecc_delta(edac_t0_obj, edac_t1, phase2_window_min)

    # ── All domain results ─────────────────────────────────────────────────
    all_domain_results = {**phase1_results, **phase2_results}

    # ── Clock Cascade Resolver — Pass 2 ───────────────────────────────────
    if "power_clocking" in all_domain_results:
        all_domain_results = resolve_clock_cascades(
            phase1_result=all_domain_results["power_clocking"],
            phase2_results=all_domain_results,
            clock_dependency_map=clock_dep_map,
        )

    # ── Confidence tagging ────────────────────────────────────────────────
    _tag_panic_confidence(all_domain_results, boot_context)
    _classify_oom_kills(all_domain_results, boot_context)

    # gate4_method5_only tagging [FINAL-S4]
    if gate4_method5_only:
        for r in all_domain_results.values():
            r.gate4_method5_only = True

    # ── Triage Agent ───────────────────────────────────────────────────────
    triage = run_triage_agent(
        domain_results=all_domain_results,
        boot_context=boot_context,
        config=config,
        api_key=api_key,
        run_id=run_id,
        board_name=board_name,
        preflight_report=preflight_report,
        edac_delta=edac_delta,
    )

    return _finalize_report(
        triage=triage,
        boot_context=boot_context,
        preflight_report=preflight_report,
        run_id=run_id,
        output_dir=output_dir,
        config=config,
        barrier_failed=False,
    )


def _finalize_report(
    triage: object,
    boot_context: dict,
    preflight_report: object,
    run_id: str,
    output_dir: str,
    config: object,
    barrier_failed: bool = False,
) -> OrchestratorResult:
    """Generate and save HTML + JSON reports."""
    verdict = getattr(triage, "po_verdict", "INCOMPLETE")
    verdict_reason = getattr(triage, "po_verdict_reason", "")
    signing_key_id = ""

    # Generate HTML report
    html_content = generate_html_report(
        triage_output=triage,
        preflight_report=preflight_report,
        boot_context=boot_context,
        run_id=run_id,
        signing_key_id=signing_key_id,
    )

    # Sign report [N-PG-02, FINAL-C1]
    signing_key = os.environ.get("POAGENT_SIGNING_KEY")
    signed_html = sign_report(html_content, run_id, signing_key)

    # Save reports
    html_path = save_html_report(signed_html, output_dir, run_id)
    json_path = save_json_report(triage, output_dir, run_id)

    exit_code = VERDICT_EXIT_CODES.get(verdict, 3)

    log.info("orchestrator_complete",
             verdict=verdict,
             exit_code=exit_code,
             html_report=html_path,
             json_report=json_path)

    return OrchestratorResult(
        verdict=verdict,
        verdict_reason=verdict_reason,
        run_id=run_id,
        html_report_path=html_path,
        json_report_path=json_path,
        exit_code=exit_code,
        barrier_failed=barrier_failed,
    )


def _cache_domain_result(result: DomainResult, output_dir: str, run_id: str) -> None:
    """Write domain result to cache for checkpoint/resume [O3]."""
    import dataclasses
    cache_dir = Path(output_dir) / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{result.domain}.json"
    try:
        data = dataclasses.asdict(result)
        cache_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        log.debug("cache_write_failed", domain=result.domain, error=str(exc))


def _run_dry_run(
    config: object,
    board_profile: object,
    clock_dep_map: dict,
    topology_warnings: list[str],
    run_id: str,
    output_dir: str,
) -> OrchestratorResult:
    """[H-02] Dry run: DTS parse + cycle detection + overlay validation only.

    No board connection. Returns exit code 5 on any validation failure.
    """
    from poagent.board.overlay_validator import validate_overlay
    errors: list[str] = []

    # Clock topology warnings
    errors.extend(topology_warnings)

    # Overlay validation
    overlay_path = getattr(config, "overlay_path", None)
    if overlay_path:
        try:
            report = validate_overlay(overlay_path)
            if not report.is_valid:
                errors.extend(report.errors)
        except Exception as exc:
            errors.append(f"Overlay validation error: {exc}")

    if errors:
        log.error("dry_run_validation_failed", errors=len(errors))
        for e in errors:
            log.error("dry_run_error", msg=e)
        return OrchestratorResult(
            verdict="INCOMPLETE",
            verdict_reason=f"DRY_RUN_VALIDATION_FAIL: {len(errors)} errors",
            run_id=run_id,
            exit_code=5,  # DRY_RUN_FAIL
            dry_run=True,
            dry_run_errors=errors,
        )

    log.info("dry_run_passed")
    return OrchestratorResult(
        verdict="PASS",
        verdict_reason="Dry run passed — DTS/overlay valid",
        run_id=run_id,
        exit_code=0,
        dry_run=True,
    )
