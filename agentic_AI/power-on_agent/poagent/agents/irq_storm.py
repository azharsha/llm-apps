"""IRQ Storm Detection — Phase 0 boot context capture.

[CG-05] /proc/interrupts delta over sample_ms window.
[N-SG-02] Normalize by online CPU count to avoid false positives on
          high-core-count SoCs (e.g. Snapdragon 8cx: 12 cores × HZ=250 = 3000/s agg,
          but only 250/CPU/s — well below 1000/CPU/s threshold).

Returns list[IRQStorm]. Never aborts the run — severity is WARNING only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from poagent.codes import IRQ_STORM_WARNING

log = structlog.get_logger(__name__)


@dataclass
class IRQLine:
    """Parsed line from /proc/interrupts."""
    irq_num: str       # e.g. "42" or "LOC" for local timer
    cpu_counts: list[int] = field(default_factory=list)
    irq_type: str = ""
    irq_trigger: str = ""
    irq_name: str = ""


@dataclass
class IRQStorm:
    """A detected IRQ storm event."""
    irq_num: str
    rate_per_cpu_per_sec: float   # normalized rate (threshold applied here)
    agg_rate_per_sec: float       # raw aggregate for debug
    online_cpu_count: int
    irq_type: str = ""
    irq_name: str = ""


def _parse_cpu_list_count(online_str: str) -> int:
    """Parse CPU list like '0-11' or '0,1,2,3' → count.

    Example: '0-11' → 12, '0,4,8' → 3, '0' → 1
    """
    count = 0
    online_str = online_str.strip()
    if not online_str:
        return 1
    for part in online_str.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                count += int(hi) - int(lo) + 1
            except ValueError:
                count += 1
        else:
            try:
                int(part)
                count += 1
            except ValueError:
                pass
    return max(count, 1)


def _parse_interrupts(content: str, cpu_count: int) -> list[IRQLine]:
    """Parse /proc/interrupts content into list of IRQLine objects."""
    lines = []
    for raw_line in content.splitlines():
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("CPU"):
            continue

        # Format: "IRQ#:  cpu0_count  cpu1_count ... type  trigger  name"
        parts = raw_line.split(":", 1)
        if len(parts) < 2:
            continue

        irq_num = parts[0].strip()
        rest = parts[1].strip()
        tokens = rest.split()
        if not tokens:
            continue

        # First N tokens should be numbers (one per CPU)
        counts: list[int] = []
        idx = 0
        while idx < len(tokens) and idx < cpu_count:
            try:
                counts.append(int(tokens[idx]))
                idx += 1
            except ValueError:
                break

        if not counts:
            continue

        # Remaining tokens: type, trigger, name
        remaining = tokens[idx:]
        irq_type = remaining[0] if len(remaining) > 0 else ""
        irq_trigger = remaining[1] if len(remaining) > 1 else ""
        irq_name = " ".join(remaining[2:]) if len(remaining) > 2 else ""

        lines.append(IRQLine(
            irq_num=irq_num,
            cpu_counts=counts,
            irq_type=irq_type,
            irq_trigger=irq_trigger,
            irq_name=irq_name,
        ))
    return lines


def check_irq_storm(
    runner: object,
    config: object,
) -> list[IRQStorm]:
    """Run IRQ storm detection.

    [N-SG-02] Reads /proc/interrupts twice, computes per-CPU rate, and
    reports any IRQ line exceeding the threshold.

    Returns list of IRQStorm entries. Empty list = no storm detected.
    """
    threshold: float = getattr(config, "irq_storm_threshold", 1000)
    sample_ms: int = getattr(config, "irq_storm_sample_ms", 1000)
    per_cpu: bool = getattr(config, "per_cpu_threshold", True)

    sample_s = sample_ms / 1000.0

    # Get online CPU count for normalization
    cpu_result = runner.exec(  # type: ignore[union-attr]
        "cat /sys/devices/system/cpu/online 2>/dev/null || echo '0'",
        timeout=2.0, probe_name="irq_cpu_online"
    )
    online_cpu_count = _parse_cpu_list_count(cpu_result.stdout.strip())

    # Snapshot 1
    snap1_result = runner.exec(  # type: ignore[union-attr]
        "cat /proc/interrupts", timeout=3.0, probe_name="irq_snap1"
    )
    snap1 = _parse_interrupts(snap1_result.stdout, online_cpu_count)

    time.sleep(sample_s)

    # Snapshot 2
    snap2_result = runner.exec(  # type: ignore[union-attr]
        "cat /proc/interrupts", timeout=3.0, probe_name="irq_snap2"
    )
    snap2 = _parse_interrupts(snap2_result.stdout, online_cpu_count)

    # Build IRQ number → line2 map for delta computation
    snap2_map: dict[str, IRQLine] = {l.irq_num: l for l in snap2}

    storms: list[IRQStorm] = []
    for line1 in snap1:
        line2 = snap2_map.get(line1.irq_num)
        if line2 is None:
            continue

        agg1 = sum(line1.cpu_counts)
        agg2 = sum(line2.cpu_counts)
        agg_delta = max(0, agg2 - agg1)  # counts are monotonic

        if sample_s <= 0:
            continue

        agg_rate = agg_delta / sample_s

        if per_cpu:
            # [N-SG-02] Per-CPU normalized rate
            rate = agg_delta / online_cpu_count / sample_s
        else:
            rate = agg_rate

        if rate >= threshold:
            storm = IRQStorm(
                irq_num=line1.irq_num,
                rate_per_cpu_per_sec=round(rate, 1),
                agg_rate_per_sec=round(agg_rate, 1),
                online_cpu_count=online_cpu_count,
                irq_type=line1.irq_type,
                irq_name=line1.irq_name,
            )
            storms.append(storm)
            log.warning(
                IRQ_STORM_WARNING,
                irq=line1.irq_num,
                irq_name=line1.irq_name,
                rate_per_cpu=round(rate, 1),
                agg_rate=round(agg_rate, 1),
                online_cpus=online_cpu_count,
            )

    if storms:
        log.warning("irq_storms_detected", count=len(storms),
                    irqs=[s.irq_num for s in storms])
    else:
        log.debug("irq_storm_check_clean", online_cpus=online_cpu_count,
                  sample_ms=sample_ms)

    return storms


def format_irq_storm_context(storms: list[IRQStorm]) -> dict:
    """Format IRQ storm list into boot_context structure."""
    if not storms:
        return {"irq_storm": None}
    return {
        "irq_storm": [
            {
                "irq": s.irq_num,
                "rate_per_cpu_per_sec": s.rate_per_cpu_per_sec,
                "agg_rate_per_sec": s.agg_rate_per_sec,
                "online_cpu_count": s.online_cpu_count,
                "type": s.irq_type,
                "name": s.irq_name,
            }
            for s in storms
        ]
    }
