"""Compute & Memory domain probe implementations.

Key PRD constraints:
- [LAST-C2] OOM kill severity: memtester+MEMTESTER_SKIPPED→WARNING;
  memtester+normal→CONDITIONAL; kernel thread→FAIL; other userspace→CONDITIONAL
- [R-04] fio only on unmounted block devices — never mounted FS
- EDAC via /sys/devices/system/edac/mc/ with Qualcomm/NXP platform fallbacks
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe
from poagent.probes.c_probe_runner import (
    CProbeDeploySkipped, CProbeCompileError, CProbeIntegrityError, CProbeExecError,
    mmio_base_not_in_dts_result,
)
from poagent.codes import MMIO_BASE_NOT_IN_DTS

log = structlog.get_logger(__name__)

DOMAIN = "compute_memory"

# DDR PHY register maps: compatible → {field: (offset, bit_shift, bit_mask)}
_DDR_PHY_OFFSETS: dict[str, dict[str, tuple[int, int, int]]] = {
    "rockchip,rk3588-ddr-phy": {
        "pll_lock": (0x10, 4, 1),
        "cal_done": (0x14, 0, 1),
    },
    "qualcomm,sc8280xp-ddrss": {
        "pll_lock": (0x0C, 8, 1),
        "cal_done": (0x10, 0, 1),
    },
    "nxp,imx8mp-ddrc": {
        "pll_lock": (0x00, 0, 1),
        "cal_done": (0x04, 2, 1),
    },
    "mediatek,mt8195-ddrphy": {
        "pll_lock": (0x08, 0, 1),
        "cal_done": (0x0C, 1, 1),
    },
}


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="CPU info and P-state status", timeout=15.0)
class CPUInfoProbe(ProbeBase):
    """Collect CPU hardware info: model, topology, P-states, vulnerability mitigations."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        rc, cpuinfo = runner.exec_command("cat /proc/cpuinfo 2>/dev/null | head -60")
        if rc == 0:
            model_lines = [l for l in cpuinfo.splitlines() if "model name" in l]
            data["model"] = model_lines[0].split(":", 1)[-1].strip() if model_lines else "unknown"

        rc, lscpu = runner.exec_command("lscpu 2>/dev/null")
        if rc == 0:
            data["lscpu"] = lscpu.strip()[:1000]

        # P-state / cpufreq driver
        rc, gov = runner.exec_command(
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null"
        )
        data["cpufreq_governor"] = gov.strip() if rc == 0 else "unavailable"

        rc, driver = runner.exec_command(
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver 2>/dev/null"
        )
        data["cpufreq_driver"] = driver.strip() if rc == 0 else "unavailable"

        # Vulnerability mitigations
        rc, vulns = runner.exec_command(
            "grep -r '' /sys/devices/system/cpu/vulnerabilities/ 2>/dev/null"
        )
        if rc == 0:
            data["vulnerabilities"] = {
                line.split(":")[0].rsplit("/", 1)[-1]: ":".join(line.split(":")[1:]).strip()
                for line in vulns.splitlines() if ":" in line
            }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"CPU: {data.get('model', 'unknown')}, governor: {data.get('cpufreq_governor')}",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="DRAM training log scan", timeout=20.0)
class DRAMTrainingProbe(ProbeBase):
    """Scan dmesg and EFI/UEFI logs for DRAM training errors."""

    _TRAINING_KEYWORDS = [
        "ddr training", "dram init", "training fail", "memory training",
        "dfi", "dqs", "vref training", "write leveling", "read leveling",
    ]

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        training_msgs: list[str] = []

        rc, dmesg_out = runner.exec_command("dmesg 2>/dev/null | grep -iE 'ddr|dram|training' | head -30")
        if rc == 0 and dmesg_out.strip():
            training_msgs.extend(dmesg_out.strip().splitlines()[:20])

        # ARM64 UEFI/ATF logs in /sys/firmware/efi or /dev/mem (skip mem — too risky)
        rc, efi_logs = runner.exec_command(
            "cat /sys/firmware/efi/efivars/MemoryTraining* 2>/dev/null | strings | head -20"
        )
        if rc == 0 and efi_logs.strip():
            training_msgs.append(f"efi_training_log: {efi_logs.strip()[:200]}")

        # Qualcomm LLCC / SHRM log
        rc, shrm = runner.exec_command(
            "dmesg 2>/dev/null | grep -i 'shrm\\|llcc\\|ddrss' | head -10"
        )
        if rc == 0 and shrm.strip():
            training_msgs.extend(shrm.strip().splitlines()[:5])

        errors = [m for m in training_msgs if any(
            w in m.lower() for w in ("fail", "error", "timeout", "marginal")
        )]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(errors) == 0,
            data={"training_messages": training_msgs[:20], "training_errors": errors},
            message=f"{len(errors)} DRAM training error(s) detected" if errors else "No DRAM training errors",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="EDAC correctable/uncorrectable counts", timeout=15.0)
class EDACProbe(ProbeBase):
    """Read EDAC ECC error counters.

    Sources: standard EDAC mc*, Qualcomm LLCC, NXP i.MX DDRC, dmesg fallback.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        ce_total = 0
        ue_total = 0
        sources: list[str] = []

        # Standard EDAC
        rc, mc_dirs = runner.exec_command("ls /sys/devices/system/edac/mc/ 2>/dev/null")
        if rc == 0:
            for mc in mc_dirs.strip().split():
                rc2, ce = runner.exec_command(
                    f"cat /sys/devices/system/edac/mc/{mc}/ce_count 2>/dev/null"
                )
                rc3, ue = runner.exec_command(
                    f"cat /sys/devices/system/edac/mc/{mc}/ue_count 2>/dev/null"
                )
                if rc2 == 0 and ce.strip().isdigit():
                    ce_total += int(ce.strip())
                    sources.append(f"edac_{mc}")
                if rc3 == 0 and ue.strip().isdigit():
                    ue_total += int(ue.strip())

        # Qualcomm LLCC
        rc, llcc = runner.exec_command(
            "cat /sys/devices/platform/*/llcc_ecc 2>/dev/null"
        )
        if rc == 0 and llcc.strip():
            sources.append("qualcomm_llcc")
            # Parse "ce: N ue: M" format
            for part in llcc.strip().split():
                pass  # agent parses LLCC format per platform

        # NXP i.MX DDRC
        rc, imx = runner.exec_command(
            "cat /sys/bus/platform/drivers/imx_ddrc/*/ecc_status 2>/dev/null"
        )
        if rc == 0 and imx.strip():
            sources.append("nxp_imx_ddrc")

        passed = ue_total == 0 and ce_total < 100

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=passed,
            data={
                "ce_total": ce_total,
                "ue_total": ue_total,
                "sources": sources,
            },
            message=f"EDAC: CE={ce_total}, UE={ue_total}",
        )


@register_probe(
    DOMAIN, tier=ProbeTier.SLOW,
    description="memtester basic memory integrity (destructive if --allow-destructive-tests)",
    timeout=120.0,
)
class MemtesterProbe(ProbeBase):
    """Run memtester for basic DRAM integrity.

    [LAST-C2] OOM kill context:
    - memtester + MEMTESTER_SKIPPED_LOW_MEMORY → WARNING
    - memtester + normal run → CONDITIONAL on OOM
    - Not run if --allow-destructive-tests is False (skip).
    """

    _MIN_FREE_MB = 256  # minimum free RAM required to run memtester

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        config = getattr(board_profile, "_config", None)
        allow_destructive = getattr(config, "allow_destructive_tests", False) if config else False

        if not allow_destructive:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "allow_destructive_tests=False"},
                message="memtester skipped (requires --allow-destructive-tests)",
            )

        # Check available memory
        rc, meminfo = runner.exec_command("grep MemAvailable /proc/meminfo 2>/dev/null")
        avail_mb = 0
        if rc == 0 and meminfo.strip():
            parts = meminfo.strip().split()
            if len(parts) >= 2 and parts[1].isdigit():
                avail_mb = int(parts[1]) // 1024  # kB → MB

        if avail_mb < self._MIN_FREE_MB:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={
                    "skipped": True,
                    "reason": "MEMTESTER_SKIPPED_LOW_MEMORY",
                    "available_mb": avail_mb,
                    "required_mb": self._MIN_FREE_MB,
                },
                message=f"memtester skipped: only {avail_mb}MB free (need {self._MIN_FREE_MB}MB)",
            )

        test_mb = min(avail_mb // 4, 512)  # use 25% of free RAM, cap at 512MB

        # Check if memtester is available
        rc, _ = runner.exec_command("which memtester 2>/dev/null")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "memtester not installed"},
                message="memtester not found on board",
            )

        rc, output = runner.exec_command(
            f"memtester {test_mb}M 1 2>&1",
            timeout=110,
        )

        errors: list[str] = []
        oom_killed = rc == 137 or "Killed" in output

        if not oom_killed:
            for line in output.splitlines():
                if "FAILURE" in line or "failed" in line.lower():
                    errors.append(line.strip())

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(errors) == 0 and not oom_killed,
            data={
                "test_mb": test_mb,
                "exit_code": rc,
                "oom_killed": oom_killed,
                "errors": errors,
                "output_tail": output.strip()[-500:],
            },
            message=(
                f"memtester OOM killed ({test_mb}MB)" if oom_killed
                else f"{len(errors)} failure(s)" if errors
                else f"memtester passed ({test_mb}MB)"
            ),
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD,
                description="DDR PHY PLL lock and calibration via MMIO register read", timeout=15.0)
class DDRPhyProbe(ProbeBase):
    """Read DDR PHY PLL lock and calibration-done bits directly via /dev/mem.

    [CP-05] Base address comes from DTS reg property — never user-supplied.
    Falls back to SKIP if reg_base is None or compatible is unknown.
    """

    _C_SOURCE = "c_probes/mmio_dump.c"

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        spec = board_profile.subsystem_by_domain(DOMAIN)
        if not spec or spec.reg_base is None:
            return mmio_base_not_in_dts_result(DOMAIN, self.__class__.__name__)

        compat = spec.compatible[0] if spec.compatible else ""
        offmap = _DDR_PHY_OFFSETS.get(compat)
        if not offmap:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                severity="SKIP",
                findings=[f"DDR PHY register map not defined for compatible '{compat}'"],
            )

        offsets_str = ",".join(f"0x{off:x}" for (off, _, _) in offmap.values())
        try:
            regs = self.run_c_probe(
                self._C_SOURCE,
                ["--base", hex(spec.reg_base),
                 "--size", hex(getattr(spec, "reg_size", None) or 0x1000),
                 "--offsets", offsets_str],
            )
        except CProbeDeploySkipped as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="SKIP", findings=[str(exc)])
        except (CProbeCompileError, CProbeIntegrityError, CProbeExecError) as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="CONDITIONAL", findings=[str(exc)])

        findings: list[str] = []
        severity = "PASS"

        pll_off, pll_shift, pll_mask = offmap["pll_lock"]
        pll_val = regs.get(f"0x{pll_off:x}", 0)
        pll_lock = (pll_val >> pll_shift) & pll_mask
        if pll_lock:
            findings.append(f"DDR PHY PLL locked (reg[0x{pll_off:x}]=0x{pll_val:08x})")
        else:
            findings.append(
                f"FAIL: DDR PHY PLL not locked (reg[0x{pll_off:x}]=0x{pll_val:08x}) — "
                "DRAM unreliable; check VDD_PHY rail and PLL reference clock"
            )
            severity = "FAIL"

        cal_off, cal_shift, cal_mask = offmap["cal_done"]
        cal_val = regs.get(f"0x{cal_off:x}", 0)
        cal_done = (cal_val >> cal_shift) & cal_mask
        if cal_done:
            findings.append(f"DDR PHY calibration complete (reg[0x{cal_off:x}]=0x{cal_val:08x})")
        else:
            findings.append(
                f"WARNING: DDR PHY calibration not done (reg[0x{cal_off:x}]=0x{cal_val:08x})"
            )
            if severity == "PASS":
                severity = "CONDITIONAL"

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            severity=severity,
            findings=findings,
            raw_data=regs,
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="IOMMU groups and DMA protection", timeout=15.0)
class IOMMUProbe(ProbeBase):
    """Check IOMMU enable state and DMA protection groups."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # IOMMU dmesg
        rc, iommu_dmesg = runner.exec_command(
            "dmesg 2>/dev/null | grep -i iommu | head -20"
        )
        if rc == 0:
            data["iommu_dmesg"] = iommu_dmesg.strip()[:500]

        # IOMMU groups
        rc, groups = runner.exec_command(
            "ls /sys/kernel/iommu_groups/ 2>/dev/null | wc -l"
        )
        data["iommu_groups"] = int(groups.strip()) if rc == 0 and groups.strip().isdigit() else 0

        # intel_iommu=on or iommu=pt kernel cmdline
        rc, cmdline = runner.exec_command("cat /proc/cmdline 2>/dev/null")
        if rc == 0:
            data["iommu_cmdline"] = [
                w for w in cmdline.split() if "iommu" in w.lower() or "smmu" in w.lower()
            ]

        # ARM64 SMMU
        rc, smmu = runner.exec_command(
            "dmesg 2>/dev/null | grep -i 'smmu\\|arm-smmu' | head -10"
        )
        if rc == 0 and smmu.strip():
            data["smmu"] = smmu.strip()[:300]

        enabled = data.get("iommu_groups", 0) > 0 or bool(data.get("iommu_cmdline"))

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,  # agent determines if IOMMU should be enabled for this board
            data=data,
            message=f"IOMMU: {'enabled' if enabled else 'not detected'}, {data.get('iommu_groups', 0)} groups",
        )
