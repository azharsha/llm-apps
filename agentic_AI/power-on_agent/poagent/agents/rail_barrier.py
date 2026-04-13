"""Rail Sanity Barrier — fast Python-only gate before Phase 1.

[CG-01] Checks critical rails (po-agent,critical) via PMBus → hwmon → regulator sysfs.
[N-CG-01] 500ms settle delay + 3-read median per rail.

RAIL_SANITY_FAIL aborts Phase 1 entirely.
BARRIER_UNCERTAIN (VDD_DDR no PMBus) allows Phase 1 with LOW_CONFIDENCE tags.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from poagent.codes import (
    RAIL_SANITY_FAIL,
    BARRIER_UNCERTAIN,
    NO_PMBUS_AVAILABLE,
)

log = structlog.get_logger(__name__)


@dataclass
class RailBarrierResult:
    """Barrier result for a single rail."""
    rail_name: str
    node_path: str
    expected_mv: int
    tolerance_pct: float
    readings_mv: list[float] = field(default_factory=list)
    median_mv: float = 0.0
    source: str = ""  # "pmbus" | "hwmon" | "regulator_sysfs" | "unavailable"
    status: str = ""  # "PASS" | "FAIL" | "UNCERTAIN" | "SKIP"
    pct_deviation: float = 0.0
    ddr_backed_warning: bool = False

    @property
    def lower_mv(self) -> float:
        return self.expected_mv * (1 - self.tolerance_pct / 100)

    @property
    def upper_mv(self) -> float:
        return self.expected_mv * (1 + self.tolerance_pct / 100)


@dataclass
class BarrierReport:
    """Result of the full Rail Sanity Barrier check."""
    timestamp: float
    settle_ms: int
    rail_results: list[RailBarrierResult] = field(default_factory=list)
    overall_status: str = "PASS"  # "PASS" | "FAIL" | "UNCERTAIN"
    uncertain_rails: list[str] = field(default_factory=list)
    failed_rails: list[str] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return self.overall_status == "PASS"

    @property
    def is_uncertain(self) -> bool:
        return self.overall_status == "UNCERTAIN"

    @property
    def is_fail(self) -> bool:
        return self.overall_status == "FAIL"

    def format_text(self) -> str:
        """Format barrier report as ASCII table."""
        lines = [
            "┌──────────────────────────────────────────────────────────────────────┐",
            f"│  PoAgent Rail Sanity Barrier "
            f"{'PASSED' if not self.is_fail else 'FAILED'}"
            f"  —  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}",
            "├──────────────────────────────────────────────────────────────────────┤",
            "│  Rail          Expected    Measured    Source      Status",
            "│  ──────────    ────────    ────────    ──────      ──────",
        ]
        for r in self.rail_results:
            icon = "✓" if r.status == "PASS" else ("?" if r.status == "UNCERTAIN" else "✗")
            pct = f"{r.pct_deviation:+.1f}%" if r.median_mv > 0 else "N/A"
            lines.append(
                f"│  {r.rail_name:<14}  {r.expected_mv:>5} mV    "
                f"{r.median_mv:>6.0f} mV    {r.source:<10}  {icon} {r.status} ({pct})"
            )
        lines.append("└──────────────────────────────────────────────────────────────────────┘")
        return "\n".join(lines)


# ── Voltage read helpers ──────────────────────────────────────────────────────

def _read_pmbus_voltage_mv(
    runner: object,
    bus: int,
    addr: int,
    page: Optional[int],
) -> Optional[float]:
    """Read rail voltage via PMBus READ_VOUT (i2cget).

    PMBus READ_VOUT (register 0x8B) returns value in LINEAR16 format.
    Returns millivolts or None on failure.
    """
    # Set page if multi-rail PMIC
    if page is not None:
        runner.exec(  # type: ignore[union-attr]
            f"i2cset -y {bus} {addr:#04x} 0x00 {page:#04x} 2>/dev/null",
            timeout=3.0, probe_name="barrier_pmbus_page"
        )
        time.sleep(0.010)

    result = runner.exec(  # type: ignore[union-attr]
        f"i2cget -y {bus} {addr:#04x} 0x8B w 2>/dev/null",
        timeout=3.0, probe_name="barrier_pmbus_read"
    )
    raw = result.stdout.strip()
    if not raw or result.returncode != 0:
        return None

    try:
        raw_val = int(raw, 16)
        # LINEAR16: mantissa in bits[10:0], exponent in bits[15:11] (signed)
        mantissa = raw_val & 0x7FF
        exponent_raw = (raw_val >> 11) & 0x1F
        # Treat as 5-bit signed
        if exponent_raw >= 16:
            exponent = exponent_raw - 32
        else:
            exponent = exponent_raw
        voltage_v = mantissa * (2 ** exponent)
        return voltage_v * 1000  # → millivolts
    except (ValueError, ZeroDivisionError):
        return None


def _read_hwmon_voltage_mv(runner: object, rail_name: str) -> Optional[float]:
    """Read rail voltage from hwmon sysfs.

    Scans /sys/class/hwmon/hwmon*/in*_label for matching rail name,
    then reads the corresponding in*_input (value in millivolts).
    """
    # Try to find by label
    result = runner.exec(  # type: ignore[union-attr]
        "grep -r '' /sys/class/hwmon/hwmon*/in*_label 2>/dev/null",
        timeout=5.0, probe_name="barrier_hwmon_labels"
    )
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        path, label = line.split(":", 1)
        if rail_name.lower() in label.lower():
            # Extract in<N>_label → in<N>_input
            input_path = path.replace("_label", "_input")
            val_result = runner.exec(  # type: ignore[union-attr]
                f"cat {input_path} 2>/dev/null",
                timeout=3.0, probe_name="barrier_hwmon_read"
            )
            try:
                return float(val_result.stdout.strip())  # already in mV
            except ValueError:
                pass

    # Fallback: scan all in*_input
    result = runner.exec(  # type: ignore[union-attr]
        "cat /sys/class/hwmon/hwmon*/in*_input 2>/dev/null | head -20",
        timeout=5.0, probe_name="barrier_hwmon_all"
    )
    # Can't match without label — return None
    return None


def _read_regulator_voltage_mv(runner: object, node_name: str) -> Optional[float]:
    """Read rail voltage from regulator sysfs (DDR-backed — last resort)."""
    # Try to match by regulator name
    result = runner.exec(  # type: ignore[union-attr]
        f"grep -r '' /sys/class/regulator/*/name 2>/dev/null | grep -i '{node_name}' | head -1",
        timeout=5.0, probe_name="barrier_regulator_name"
    )
    if result.stdout.strip() and ":" in result.stdout:
        path = result.stdout.split(":")[0]
        reg_dir = path.replace("/name", "")
        val_result = runner.exec(  # type: ignore[union-attr]
            f"cat {reg_dir}/microvolts 2>/dev/null",
            timeout=3.0, probe_name="barrier_regulator_read"
        )
        try:
            return float(val_result.stdout.strip()) / 1000.0  # µV → mV
        except ValueError:
            pass
    return None


def _read_rail_voltage_median(
    runner: object,
    rail: object,
    read_interval_s: float = 0.100,
    num_reads: int = 3,
) -> tuple[float, str, bool]:
    """Read rail voltage 3 times at 100ms spacing. Return (median_mv, source, ddr_backed).

    Priority: PMBus → hwmon → regulator_sysfs.
    """
    readings: list[float] = []
    source = "unavailable"
    ddr_backed = False

    rail_name = getattr(rail, "name", "")
    pmbus_bus = getattr(rail, "pmbus_bus", None)
    pmbus_addr = getattr(rail, "pmbus_addr", None)
    pmbus_page = getattr(rail, "pmbus_vout_page", None)

    for i in range(num_reads):
        mv: Optional[float] = None

        # Priority 1: PMBus
        if pmbus_bus is not None and pmbus_addr is not None:
            mv = _read_pmbus_voltage_mv(runner, pmbus_bus, pmbus_addr, pmbus_page)
            if mv is not None and source == "unavailable":
                source = "pmbus"

        # Priority 2: hwmon
        if mv is None:
            mv = _read_hwmon_voltage_mv(runner, rail_name)
            if mv is not None and source == "unavailable":
                source = "hwmon"

        # Priority 3: regulator sysfs
        if mv is None:
            node_name = getattr(rail, "node_path", rail_name).split("/")[-1]
            mv = _read_regulator_voltage_mv(runner, node_name)
            if mv is not None and source == "unavailable":
                source = "regulator_sysfs"
                ddr_backed = True

        if mv is not None:
            readings.append(mv)

        if i < num_reads - 1:
            time.sleep(read_interval_s)

    if not readings:
        return 0.0, "unavailable", False

    median_mv = float(sorted(readings)[len(readings) // 2])
    return median_mv, source, ddr_backed


# ── Main barrier function ─────────────────────────────────────────────────────

def run_rail_barrier(
    runner: object,
    board_profile: object,
    config: object,
) -> BarrierReport:
    """Run the Rail Sanity Barrier.

    [N-CG-01] Settle delay + 3-read median per rail.
    Returns BarrierReport. FAIL status requires caller to abort Phase 1.
    """
    settle_ms: int = getattr(config, "barrier_pre_read_settle_ms", 500)
    report = BarrierReport(timestamp=time.time(), settle_ms=settle_ms)

    critical_rails = list(getattr(board_profile, "critical_rails", lambda: [])())
    if not critical_rails:
        log.warning("barrier_no_critical_rails",
                    msg="No po-agent,critical rails in overlay — barrier skipped")
        report.overall_status = "PASS"
        return report

    log.info("barrier_starting",
             settle_ms=settle_ms, rail_count=len(critical_rails))

    # [N-CG-01] Settle delay before any read
    time.sleep(settle_ms / 1000.0)

    for rail in critical_rails:
        rail_name = getattr(rail, "name", "unknown")
        expected_mv = getattr(rail, "expected_mv", 0)
        tolerance_pct = float(getattr(rail, "tolerance_pct", 5))

        rr = RailBarrierResult(
            rail_name=rail_name,
            node_path=getattr(rail, "node_path", ""),
            expected_mv=expected_mv,
            tolerance_pct=tolerance_pct,
        )

        median_mv, source, ddr_backed = _read_rail_voltage_median(runner, rail)
        rr.source = source
        rr.ddr_backed_warning = ddr_backed

        if source == "unavailable" or median_mv == 0.0:
            # Special case: VDD_DDR with no PMBus → UNCERTAIN
            if "ddr" in rail_name.lower() or "mem" in rail_name.lower():
                rr.status = "UNCERTAIN"
                rr.readings_mv = []
                rr.median_mv = 0.0
                report.uncertain_rails.append(rail_name)
                log.warning(NO_PMBUS_AVAILABLE, rail=rail_name,
                            msg=f"{BARRIER_UNCERTAIN}: no DDR-independent voltage source")
            else:
                rr.status = "SKIP"
                log.debug("barrier_rail_skip", rail=rail_name,
                          reason="no voltage source found")
        else:
            rr.median_mv = median_mv
            lower = expected_mv * (1 - tolerance_pct / 100)
            upper = expected_mv * (1 + tolerance_pct / 100)

            if lower <= median_mv <= upper:
                rr.status = "PASS"
                rr.pct_deviation = (median_mv - expected_mv) / expected_mv * 100
            else:
                rr.status = "FAIL"
                rr.pct_deviation = (median_mv - expected_mv) / expected_mv * 100
                report.failed_rails.append(rail_name)
                log.error(RAIL_SANITY_FAIL, rail=rail_name,
                          expected_mv=expected_mv, median_mv=median_mv,
                          pct=round(rr.pct_deviation, 2))

            if ddr_backed:
                log.warning("barrier_ddr_backed_read", rail=rail_name,
                            msg="regulator sysfs used — result unreliable if DDR marginal")

        report.rail_results.append(rr)

    # Determine overall status
    if report.failed_rails:
        report.overall_status = "FAIL"
    elif report.uncertain_rails:
        report.overall_status = "UNCERTAIN"
    else:
        report.overall_status = "PASS"

    log.info("barrier_complete",
             status=report.overall_status,
             failed=report.failed_rails,
             uncertain=report.uncertain_rails)

    return report
