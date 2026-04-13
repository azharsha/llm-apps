"""EDAC ECC rate tracking — Phase 0 baseline + Phase 2 delta.

[CG-06] Snapshot at Phase 0 (before agents) and after Phase 2.
Delta + rate determine DRAM_MARGINAL (>100 CE/min) or DRAM_UNCORRECTABLE.

[N-SG-01] Multi-source ECC read: EDAC → Qualcomm LLCC → NXP DDRC → dmesg.
No source found → ECC_NOT_MONITORABLE (never silent PASS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

from poagent.codes import (
    DRAM_MARGINAL,
    DRAM_UNCORRECTABLE_ERROR,
    ECC_NOT_MONITORABLE,
)

log = structlog.get_logger(__name__)


@dataclass
class EccSnapshot:
    """ECC count snapshot from a single read."""
    ce: Optional[int] = None   # correctable error count (None if unavailable)
    ue: Optional[int] = None   # uncorrectable error count (None if unavailable)
    source: str = "unavailable"  # "edac_mc" | "qualcomm_llcc" | "nxp_imx_ddrc" | "dmesg_keyword" | "unavailable"
    raw_log: str = ""          # for dmesg_keyword source
    note: str = ""             # explanatory note
    counters: dict[str, int] = field(default_factory=dict)  # per-mc detailed counts


@dataclass
class EccDeltaReport:
    """Result of ECC delta analysis."""
    t0: EccSnapshot
    t1: EccSnapshot
    window_min: float           # diagnostic window in minutes
    ce_delta: Optional[int] = None
    ue_delta: Optional[int] = None
    ce_rate_per_min: Optional[float] = None
    dram_marginal: bool = False
    dram_uncorrectable: bool = False
    ecc_not_monitorable: bool = False

    @property
    def source(self) -> str:
        return self.t0.source


# ── ECC read functions ────────────────────────────────────────────────────────

def _parse_llcc_ecc(content: str) -> tuple[int, int]:
    """Parse Qualcomm LLCC ECC sysfs output → (ce, ue)."""
    ce = ue = 0
    for line in content.splitlines():
        line = line.lower().strip()
        if "correctable" in line and "un" not in line:
            m = re.search(r"(\d+)", line)
            if m:
                ce += int(m.group(1))
        elif "uncorrectable" in line:
            m = re.search(r"(\d+)", line)
            if m:
                ue += int(m.group(1))
    return ce, ue


def _parse_imx_ddrc_ecc(content: str) -> tuple[int, int]:
    """Parse NXP i.MX DDRC ECC sysfs → (ce, ue)."""
    ce = ue = 0
    for line in content.splitlines():
        line_l = line.lower().strip()
        m = re.search(r"(\d+)", line)
        if not m:
            continue
        val = int(m.group(1))
        if "ce" in line_l or "correctable" in line_l:
            if "un" not in line_l:
                ce += val
            else:
                ue += val
    return ce, ue


def read_edac_counts(runner: object) -> EccSnapshot:
    """Read ECC counts from available source.

    [N-SG-01] Priority: EDAC mc → Qualcomm LLCC → NXP DDRC → dmesg.
    """
    # Source 1: Standard EDAC framework
    if runner.path_exists("/sys/devices/system/edac/mc/"):  # type: ignore[union-attr]
        try:
            ce_vals = runner.glob_read(  # type: ignore[union-attr]
                "/sys/devices/system/edac/mc/mc*/ce_count"
            )
            ue_vals = runner.glob_read(  # type: ignore[union-attr]
                "/sys/devices/system/edac/mc/mc*/ue_count"
            )
            ce = sum(int(v.strip()) for v in ce_vals if v.strip().isdigit())
            ue = sum(int(v.strip()) for v in ue_vals if v.strip().isdigit())

            # Per-mc breakdown
            counters: dict[str, int] = {}
            mc_dirs = runner.glob("/sys/devices/system/edac/mc/mc*")  # type: ignore[union-attr]
            for mc_dir in mc_dirs:
                mc_name = mc_dir.split("/")[-1]
                ce_raw = runner.read_file(f"{mc_dir}/ce_count")  # type: ignore[union-attr]
                ue_raw = runner.read_file(f"{mc_dir}/ue_count")  # type: ignore[union-attr]
                try:
                    counters[f"{mc_name}_ce"] = int(ce_raw.strip())
                    counters[f"{mc_name}_ue"] = int(ue_raw.strip())
                except ValueError:
                    pass

            log.debug("edac_read_mc", ce=ce, ue=ue)
            return EccSnapshot(ce=ce, ue=ue, source="edac_mc", counters=counters)
        except Exception as exc:
            log.debug("edac_mc_read_failed", error=str(exc))

    # Source 2: Qualcomm LLCC ECC sysfs
    try:
        llcc_paths = runner.glob("/sys/devices/platform/*/llcc_ecc")  # type: ignore[union-attr]
        if llcc_paths:
            content = runner.read_file(llcc_paths[0])  # type: ignore[union-attr]
            ce, ue = _parse_llcc_ecc(content)
            log.debug("edac_read_llcc", ce=ce, ue=ue)
            return EccSnapshot(ce=ce, ue=ue, source="qualcomm_llcc")
    except Exception as exc:
        log.debug("edac_llcc_read_failed", error=str(exc))

    # Source 3: NXP i.MX DDRC
    try:
        imx_paths = runner.glob(  # type: ignore[union-attr]
            "/sys/bus/platform/drivers/imx_ddrc/*/ecc_status"
        )
        if imx_paths:
            content = runner.read_file(imx_paths[0])  # type: ignore[union-attr]
            ce, ue = _parse_imx_ddrc_ecc(content)
            log.debug("edac_read_imx_ddrc", ce=ce, ue=ue)
            return EccSnapshot(ce=ce, ue=ue, source="nxp_imx_ddrc")
    except Exception as exc:
        log.debug("edac_imx_read_failed", error=str(exc))

    # Source 4: dmesg keyword fallback
    try:
        result = runner.exec(  # type: ignore[union-attr]
            "dmesg | grep -iE 'ecc|uncorrectable|correctable error' 2>/dev/null",
            timeout=5.0, probe_name="edac_dmesg"
        )
        if result.stdout.strip():
            log.debug("edac_read_dmesg_keyword")
            return EccSnapshot(
                ce=None, ue=None, source="dmesg_keyword",
                raw_log=result.stdout,
                note="count unavailable — delta tracking disabled"
            )
    except Exception as exc:
        log.debug("edac_dmesg_read_failed", error=str(exc))

    # No ECC source found
    log.warning(ECC_NOT_MONITORABLE)
    return EccSnapshot(
        ce=None, ue=None, source="unavailable",
        note=f"{ECC_NOT_MONITORABLE}: no EDAC, LLCC, or DDRC driver bound"
    )


def compute_ecc_delta(
    t0: EccSnapshot,
    t1: EccSnapshot,
    window_min: float,
    marginal_threshold_per_min: float = 100.0,
) -> EccDeltaReport:
    """Compute ECC delta and issue DRAM_MARGINAL / DRAM_UNCORRECTABLE if needed.

    [CG-06] ecc_ce_rate > 100/min → DRAM_MARGINAL.
    ecc_ue_delta > 0 → DRAM_UNCORRECTABLE.
    """
    report = EccDeltaReport(t0=t0, t1=t1, window_min=window_min)

    if t0.source == "unavailable" or t1.source == "unavailable":
        report.ecc_not_monitorable = True
        return report

    if t0.source == "dmesg_keyword" or t1.source == "dmesg_keyword":
        # Delta tracking disabled for dmesg keyword source
        report.ecc_not_monitorable = False
        return report

    if t0.ce is not None and t1.ce is not None:
        report.ce_delta = max(0, t1.ce - t0.ce)
        if window_min > 0:
            report.ce_rate_per_min = report.ce_delta / window_min
            if report.ce_rate_per_min > marginal_threshold_per_min:
                report.dram_marginal = True
                log.warning(DRAM_MARGINAL,
                            ce_rate=round(report.ce_rate_per_min, 2),
                            threshold=marginal_threshold_per_min)

    if t0.ue is not None and t1.ue is not None:
        report.ue_delta = max(0, t1.ue - t0.ue)
        if report.ue_delta > 0:
            report.dram_uncorrectable = True
            log.error(DRAM_UNCORRECTABLE_ERROR, ue_delta=report.ue_delta)

    return report
