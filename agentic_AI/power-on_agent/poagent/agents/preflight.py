"""Pre-flight gate checks — Gates 1–6.

[PRD §3] Hard gates that must all pass before any diagnostic agent launches.
Gates run in strict order. Failure at any critical gate aborts immediately.

Gate 1: Board Powered On (PDU/BMC + ping fallback)
Gate 2: U-Boot → Kernel Handoff (/proc/version poll with retry)
Gate 3: SSH / Serial Console Reachable (echo poagent_ready)
Gate 4: Userspace Ready (systemd / SysVinit / BusyBox / sentinel)
Gate 5: DTS Peripherals Visible in Sysfs (with DTS version cross-check)
Gate 6: Debugfs Mounted (WARNING only, never abort)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from poagent.codes import (
    GATE4_METHOD5_ONLY,
    GATE4_SENTINEL_UNSTABLE,
    DTS_VERSION_MISMATCH_WARNING,
    ENUM_FAIL,
    SKIP_NOT_POPULATED,
)

log = structlog.get_logger(__name__)


class PreFlightError(Exception):
    """Raised when a critical pre-flight gate fails."""


@dataclass
class GateResult:
    """Result of a single gate check."""
    gate_num: int
    name: str
    passed: bool
    severity: str  # "PASS" | "FAIL" | "WARNING" | "SKIP"
    detail: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class PreFlightReport:
    """Aggregated result of all pre-flight gates."""
    board_name: str
    board_ip: str
    timestamp: float
    gates: list[GateResult] = field(default_factory=list)
    abort_gate: Optional[int] = None
    abort_reason: str = ""
    debugfs_available: bool = True
    enum_failures: list[str] = field(default_factory=list)
    gate4_method5_only: bool = False
    dts_version_mismatch: Optional[dict] = None

    @property
    def all_critical_passed(self) -> bool:
        return self.abort_gate is None

    def format_text(self) -> str:
        """Format the pre-flight report as ASCII table."""
        lines = [
            "┌──────────────────────────────────────────────────────────────┐",
            f"│  PoAgent Pre-Flight {'PASSED' if self.all_critical_passed else 'FAILED'}"
            f"  —  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}",
            f"│  Board: {self.board_name}  │  Host: {self.board_ip}",
            "├──────────────────────────────────────────────────────────────┤",
        ]
        for g in self.gates:
            icon = "✓" if g.passed else ("─" if g.severity == "SKIP" else "✗")
            lines.append(f"│  Gate {g.gate_num}  {g.name:<30}  {icon} {g.severity}")
            if g.detail:
                lines.append(f"│          {g.detail}")
        lines.append("└──────────────────────────────────────────────────────────┘")
        return "\n".join(lines)


# ── Gate 1: Board Powered On ──────────────────────────────────────────────────

def check_gate1_power(runner: object, config: object) -> GateResult:
    """Gate 1: Board Powered On.

    Primary: PDU/BMC (IPMI, Redfish, SNMP).
    Fallback: ping + SSH connectivity from Gate 3.
    """
    bmc_host: str = getattr(config, "bmc_host", "") or ""
    pdu_host: str = getattr(config, "pdu_host", "") or ""

    if bmc_host:
        # Try IPMI
        result = runner.exec(  # type: ignore[union-attr]
            f"ipmitool -H {bmc_host} chassis status 2>/dev/null | grep 'System Power'",
            timeout=10.0,
            probe_name="gate1_ipmi",
        )
        if "on" in result.stdout.lower():
            return GateResult(1, "Board power (IPMI)", True, "PASS",
                              f"IPMI: System Power On ({bmc_host})")
        return GateResult(1, "Board power (IPMI)", False, "FAIL",
                          f"IPMI power state not 'on': {result.stdout.strip()[:60]}")

    if pdu_host:
        pdu_outlet = getattr(config, "pdu_outlet", "1")
        result = runner.exec(  # type: ignore[union-attr]
            f"snmpget -v2c -c public {pdu_host} {pdu_outlet} 2>/dev/null",
            timeout=10.0,
            probe_name="gate1_pdu",
        )
        if result.returncode == 0 and result.stdout.strip().endswith("1"):
            return GateResult(1, "Board power (PDU)", True, "PASS",
                              f"PDU outlet ON ({pdu_host})")
        return GateResult(1, "Board power (PDU)", False, "FAIL",
                          f"PDU outlet not ON: {result.stdout.strip()[:60]}")

    # Fallback: ping
    board_ip: str = getattr(config, "board_ip", "") or getattr(runner, "_board_ip", "")
    if board_ip:
        import subprocess
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "2", board_ip],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                return GateResult(1, "Board power (ping)", True, "PASS",
                                  f"ICMP reply from {board_ip}")
        except Exception as exc:
            return GateResult(1, "Board power (ping)", False, "FAIL",
                              f"Ping failed: {exc}")
        return GateResult(1, "Board power (ping)", False, "FAIL",
                          f"No ICMP reply from {board_ip}")

    # No PDU/BMC/IP configured: assume power is on (Gate 3 SSH is implicit check)
    log.debug("gate1_no_power_check_configured")
    return GateResult(1, "Board power", True, "PASS",
                      "No PDU/BMC configured — relying on SSH reachability (Gate 3)")


# ── Gate 2: Kernel Handoff ────────────────────────────────────────────────────

def check_gate2_kernel(runner: object, config: object) -> GateResult:
    """Gate 2: U-Boot → Kernel Handoff.

    Poll /proc/version every 5s for up to boot_wait_timeout seconds.
    """
    timeout_s: int = getattr(config, "boot_wait_timeout", 180)
    deadline = time.time() + timeout_s
    attempt = 0

    while time.time() < deadline:
        result = runner.exec(  # type: ignore[union-attr]
            "cat /proc/version 2>/dev/null", timeout=5.0, probe_name="gate2_version"
        )
        if "Linux version" in result.stdout:
            kernel_str = result.stdout.strip().split("\n")[0][:80]
            elapsed = int(time.time() - (deadline - timeout_s))
            return GateResult(2, "Kernel handoff", True, "PASS",
                              f"{kernel_str} (+{elapsed}s)")
        attempt += 1
        remaining = deadline - time.time()
        if remaining > 5:
            time.sleep(5)

    return GateResult(2, "Kernel handoff", False, "FAIL",
                      f"/proc/version not found within {timeout_s}s boot_wait_timeout")


# ── Gate 3: SSH Reachable ─────────────────────────────────────────────────────

def check_gate3_ssh(runner: object, config: object) -> GateResult:
    """Gate 3: SSH / Serial console reachable.

    Runner is already connected at this point (via_ssh or via_serial).
    Just verify echo round-trip.
    """
    result = runner.exec(  # type: ignore[union-attr]
        "echo poagent_ready", timeout=10.0, probe_name="gate3_echo"
    )
    if "poagent_ready" in result.stdout:
        transport = getattr(runner, "_transport_type", "unknown")
        return GateResult(3, "Console reachable", True, "PASS",
                          f"echo OK via {transport}")
    return GateResult(3, "Console reachable", False, "FAIL",
                      f"echo poagent_ready failed: stdout={result.stdout!r:.60}")


# ── Gate 4: Userspace Ready ───────────────────────────────────────────────────

def check_gate4_userspace(runner: object, config: object) -> tuple[GateResult, bool]:
    """Gate 4: Userspace Ready.

    Returns (GateResult, gate4_method5_only).
    Tries systemd → journalctl → SysVinit → BusyBox sentinel → uptime → Method 5.
    """
    # Method 1: systemd
    result = runner.exec(  # type: ignore[union-attr]
        "systemctl is-active multi-user.target 2>/dev/null", timeout=5.0,
        probe_name="gate4_systemd"
    )
    if result.stdout.strip() == "active":
        return GateResult(4, "Userspace ready", True, "PASS",
                          "systemd: multi-user.target active"), False

    # Method 2: journalctl
    result = runner.exec(  # type: ignore[union-attr]
        "journalctl -b --no-pager -q -g 'Reached target.*[Mm]ulti.[Uu]ser' 2>/dev/null | head -1",
        timeout=5.0, probe_name="gate4_journalctl"
    )
    if result.stdout.strip():
        return GateResult(4, "Userspace ready", True, "PASS",
                          "journalctl: multi-user.target reached"), False

    # Method 3: SysVinit
    result = runner.exec(  # type: ignore[union-attr]
        "ls /etc/rc.d/rc3.d/S* 2>/dev/null | head -1 || ls /var/lock/subsys/ 2>/dev/null | head -1",
        timeout=5.0, probe_name="gate4_sysvinit"
    )
    if result.stdout.strip():
        return GateResult(4, "Userspace ready", True, "PASS",
                          "SysVinit: rc3.d init scripts found"), False

    # Method 4: BusyBox / minimal init
    sentinel_path: str = getattr(config, "gate4_sentinel_path", "/tmp/poagent_ready")
    stable_count: int = getattr(config, "gate4_sentinel_stable_count", 3)

    # 4a: check init PID
    result = runner.exec(  # type: ignore[union-attr]
        "ps | grep -v grep | grep -E 'init|s6|runit|openrc' | head -1 2>/dev/null",
        timeout=3.0, probe_name="gate4_ps"
    )
    init_found = bool(result.stdout.strip())

    # 4b: sentinel stability check
    sentinel_ok = _check_sentinel_stable(runner, sentinel_path, stable_count)

    # 4c: uptime sanity
    min_uptime: int = getattr(config, "min_uptime_seconds", 10)
    result = runner.exec(  # type: ignore[union-attr]
        "cat /proc/uptime 2>/dev/null | awk '{print $1}'",
        timeout=3.0, probe_name="gate4_uptime"
    )
    try:
        uptime_s = float(result.stdout.strip())
        uptime_ok = uptime_s >= min_uptime
    except (ValueError, TypeError):
        uptime_ok = False

    if sentinel_ok and uptime_ok:
        return GateResult(4, "Userspace ready", True, "PASS",
                          f"BusyBox: sentinel OK + uptime {uptime_s:.0f}s"), False

    if init_found and uptime_ok:
        detail = f"init process found, uptime={uptime_s:.0f}s"
        if not sentinel_ok:
            detail += f" (sentinel {sentinel_path} not stable — {GATE4_SENTINEL_UNSTABLE})"
        return GateResult(4, "Userspace ready", True, "PASS", detail), False

    # Method 5: universal last resort
    result = runner.exec(  # type: ignore[union-attr]
        "ls /proc/1/fd 2>/dev/null | wc -l", timeout=3.0, probe_name="gate4_proc1"
    )
    try:
        fd_count = int(result.stdout.strip())
    except (ValueError, TypeError):
        fd_count = 0

    cmdline_result = runner.exec(  # type: ignore[union-attr]
        "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' '", timeout=3.0,
        probe_name="gate4_cmdline"
    )
    cmdline = cmdline_result.stdout.strip()
    if fd_count > 5 and cmdline and "swapper" not in cmdline:
        log.warning(GATE4_METHOD5_ONLY, sentinel_path=sentinel_path)
        return GateResult(4, "Userspace ready", True, "WARNING",
                          f"{GATE4_METHOD5_ONLY}: PID1 running (fd={fd_count}), "
                          f"init type unknown. Results may be incomplete."), True

    return GateResult(4, "Userspace ready", False, "FAIL",
                      "All userspace detection methods failed"), False


def _check_sentinel_stable(runner: object, path: str, count: int) -> bool:
    """Check sentinel file exists `count` times with 2s spacing."""
    successes = 0
    for i in range(count):
        result = runner.exec(  # type: ignore[union-attr]
            f"test -f {path} && echo yes || echo no",
            timeout=3.0, probe_name="gate4_sentinel"
        )
        if result.stdout.strip() == "yes":
            successes += 1
        if i < count - 1:
            time.sleep(2.0)
    return successes == count


# ── Gate 5: DTS Sysfs Cross-Check ────────────────────────────────────────────

def check_gate5_sysfs(
    runner: object,
    config: object,
    board_profile: object,
) -> tuple[GateResult, list[str], Optional[dict]]:
    """Gate 5: DTS-declared peripherals visible in sysfs.

    Returns (GateResult, enum_failure_list, dts_version_mismatch_dict).

    [SG-07] First performs DTS kernel version cross-check.
    """
    # DTS kernel version cross-check [SG-07]
    dts_version_mismatch = None
    dts_kernel_version = getattr(board_profile, "dts_kernel_version", None)

    if dts_kernel_version:
        result = runner.exec(  # type: ignore[union-attr]
            "cat /proc/version 2>/dev/null", timeout=5.0, probe_name="gate5_procver"
        )
        running_version = _parse_kernel_version(result.stdout)
        if running_version and running_version != dts_kernel_version:
            dts_version_mismatch = {
                "dts_version": dts_kernel_version,
                "kernel_version": running_version,
            }
            log.warning(DTS_VERSION_MISMATCH_WARNING,
                        dts=dts_kernel_version, running=running_version)

    subsystems = getattr(board_profile, "subsystems", [])
    passed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    for sub in subsystems:
        # Skip physically absent peripherals
        if not getattr(sub, "physically_present", True):
            skipped.append(sub.name)
            log.debug(SKIP_NOT_POPULATED, subsystem=sub.name)
            continue

        sysfs_glob = getattr(sub, "sysfs_glob", "")
        if not sysfs_glob:
            continue

        result = runner.exec(  # type: ignore[union-attr]
            f"ls -d {sysfs_glob} 2>/dev/null | head -1",
            timeout=5.0, probe_name="gate5_sysfs"
        )
        if result.stdout.strip():
            passed.append(sub.name)
        else:
            failed.append(sub.name)
            log.debug(ENUM_FAIL, subsystem=sub.name, glob=sysfs_glob)

    total = len(passed) + len(failed)
    if total == 0:
        # No DTS subsystems to check — pass trivially
        return (
            GateResult(5, "Sysfs cross-check", True, "PASS",
                       "No DTS subsystems with known sysfs mappings"),
            [],
            dts_version_mismatch,
        )

    if len(failed) == total:
        return (
            GateResult(5, "Sysfs cross-check", False, "FAIL",
                       f"ALL {total} DTS subsystems missing from sysfs — "
                       "sysfs not mounted or kernel panic"),
            failed,
            dts_version_mismatch,
        )

    detail = f"{len(passed)}/{total} DTS subsystems visible"
    if failed:
        detail += f"; ENUM_FAIL: {', '.join(failed[:5])}"
        if len(failed) > 5:
            detail += f" (+{len(failed) - 5} more)"
    severity = "WARNING" if failed else "PASS"
    return (
        GateResult(5, "Sysfs cross-check", True, severity, detail),
        failed,
        dts_version_mismatch,
    )


def _parse_kernel_version(proc_version: str) -> Optional[str]:
    """Extract 'MAJOR.MINOR' from /proc/version string."""
    m = re.search(r"Linux version (\d+)\.(\d+)", proc_version)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


# ── Gate 6: Debugfs ───────────────────────────────────────────────────────────

def check_gate6_debugfs(runner: object, config: object) -> tuple[GateResult, bool]:
    """Gate 6: Debugfs mounted.

    Returns (GateResult, debugfs_available).
    Never aborts — only WARNING.
    """
    # Check if mounted
    result = runner.exec(  # type: ignore[union-attr]
        "mount 2>/dev/null | grep 'debugfs on /sys/kernel/debug'",
        timeout=5.0, probe_name="gate6_mount"
    )
    if result.stdout.strip():
        return (
            GateResult(6, "Debugfs mounted", True, "PASS",
                       "debugfs mounted at /sys/kernel/debug"),
            True,
        )

    # Try to mount
    result = runner.exec(  # type: ignore[union-attr]
        "mount -t debugfs none /sys/kernel/debug 2>&1",
        timeout=5.0, probe_name="gate6_mount_attempt"
    )
    # Re-check
    recheck = runner.exec(  # type: ignore[union-attr]
        "mount 2>/dev/null | grep 'debugfs on /sys/kernel/debug'",
        timeout=3.0, probe_name="gate6_recheck"
    )
    if recheck.stdout.strip():
        return (
            GateResult(6, "Debugfs mounted", True, "PASS",
                       "debugfs mounted by poagent"),
            True,
        )

    log.warning("debugfs_unavailable", error=result.stdout.strip()[:80])
    return (
        GateResult(6, "Debugfs mounted", False, "WARNING",
                   f"debugfs unavailable — debugfs-dependent probes will be skipped. "
                   f"({result.stdout.strip()[:60]})"),
        False,
    )


# ── Orchestrated Pre-Flight Run ───────────────────────────────────────────────

def run_preflight(
    runner: object,
    config: object,
    board_profile: object,
) -> PreFlightReport:
    """Run all 6 pre-flight gates in order.

    Returns PreFlightReport. Raises PreFlightError on critical gate failure.
    """
    board_name: str = getattr(config, "board_name", "") or getattr(board_profile, "board_name", "unknown")
    board_ip: str = getattr(config, "board_ip", "")

    report = PreFlightReport(
        board_name=board_name,
        board_ip=board_ip,
        timestamp=time.time(),
    )

    # Gate 1
    g1 = check_gate1_power(runner, config)
    report.gates.append(g1)
    if not g1.passed:
        report.abort_gate = 1
        report.abort_reason = g1.detail
        log.error("preflight_abort", gate=1, reason=g1.detail)
        raise PreFlightError(f"Gate 1 FAILED: {g1.detail}")

    # Gate 2
    g2 = check_gate2_kernel(runner, config)
    report.gates.append(g2)
    if not g2.passed:
        report.abort_gate = 2
        report.abort_reason = g2.detail
        raise PreFlightError(f"Gate 2 FAILED: {g2.detail}")

    # Gate 3
    g3 = check_gate3_ssh(runner, config)
    report.gates.append(g3)
    if not g3.passed:
        report.abort_gate = 3
        report.abort_reason = g3.detail
        raise PreFlightError(f"Gate 3 FAILED: {g3.detail}")

    # Gate 4
    g4, method5_only = check_gate4_userspace(runner, config)
    report.gates.append(g4)
    report.gate4_method5_only = method5_only
    if not g4.passed:
        report.abort_gate = 4
        report.abort_reason = g4.detail
        raise PreFlightError(f"Gate 4 FAILED: {g4.detail}")

    # Gate 5
    g5, enum_failures, dts_mismatch = check_gate5_sysfs(runner, config, board_profile)
    report.gates.append(g5)
    report.enum_failures = enum_failures
    report.dts_version_mismatch = dts_mismatch
    if g5.severity == "FAIL":
        report.abort_gate = 5
        report.abort_reason = g5.detail
        raise PreFlightError(f"Gate 5 FAILED: {g5.detail}")

    # Gate 6 — never aborts
    g6, debugfs_available = check_gate6_debugfs(runner, config)
    report.gates.append(g6)
    report.debugfs_available = debugfs_available

    log.info("preflight_complete",
             board=board_name,
             enum_failures=len(enum_failures),
             debugfs=debugfs_available,
             gate4_method5_only=method5_only)

    return report
