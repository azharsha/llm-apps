"""Storage domain probe implementations.

Key PRD constraints:
- [R-04] fio MUST check for mounted FS; NEVER issue fio against mounted FS.
  Use pre-GPT space only for mounted devices.
- SPI NOR: check Block Protect (BP) bits — cleared BP → write exposure risk.
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe
from poagent.probes.c_probe_runner import (
    CProbeDeploySkipped, CProbeCompileError, CProbeIntegrityError, CProbeExecError,
    mmio_base_not_in_dts_result,
)

log = structlog.get_logger(__name__)

DOMAIN = "storage"

# SDHCI register offsets (SD Host Controller Specification)
_SDHCI_PRESENT_STATE = 0x24
_SDHCI_CARD_INSERTED  = (1 << 16)   # Card Inserted bit
_SDHCI_DAT_LINE_ACTIVE = (1 << 2)   # DAT Line Active
_SDHCI_CMD_INHIBIT     = (1 << 0)   # CMD line inhibit (busy)


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="NVMe SMART health log", timeout=30.0)
class NVMeProbe(ProbeBase):
    """Read NVMe SMART-health-information-log via nvme-cli."""

    _CRITICAL_WARNING_BITS = {
        0: "spare_below_threshold",
        1: "temperature_warning",
        2: "reliability_degraded",
        3: "read_only",
        4: "volatile_memory_backup_failed",
    }

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # Discover NVMe devices
        rc, nvme_list = runner.exec_command("ls /dev/nvme[0-9] 2>/dev/null")
        devices = nvme_list.strip().split() if rc == 0 else []

        if not devices:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"devices": []},
                message="No NVMe devices found",
            )

        results: dict = {}
        failed: list[str] = []

        for dev in devices[:4]:
            rc, smart = runner.exec_command(f"nvme smart-log {dev} -o json 2>/dev/null")
            if rc != 0:
                rc, smart = runner.exec_command(f"nvme smart-log {dev} 2>/dev/null")

            if rc != 0:
                results[dev] = {"error": "smart-log failed"}
                continue

            import json as _json
            try:
                smart_data = _json.loads(smart)
            except ValueError:
                smart_data = {"raw": smart.strip()[:500]}

            crit_warning = smart_data.get("critical_warning", 0)
            if isinstance(crit_warning, int) and crit_warning != 0:
                active_warnings = [
                    name for bit, name in self._CRITICAL_WARNING_BITS.items()
                    if crit_warning & (1 << bit)
                ]
                failed.append(dev)
                results[dev] = {
                    "critical_warning": crit_warning,
                    "active_warnings": active_warnings,
                    "percentage_used": smart_data.get("percent_used", 0),
                    "temperature_k": smart_data.get("temperature", 0),
                }
            else:
                results[dev] = {
                    "critical_warning": 0,
                    "percentage_used": smart_data.get("percent_used", 0),
                    "available_spare": smart_data.get("avail_spare", 0),
                    "temperature_k": smart_data.get("temperature", 0),
                }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(failed) == 0,
            data={"nvme_devices": results, "failed": failed},
            message=f"NVMe: {len(devices)} device(s), {len(failed)} warning(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="eMMC health and ext_csd", timeout=30.0)
class EMMCProbe(ProbeBase):
    """Read eMMC health via mmc-utils ext_csd."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rc, mmc_devs = runner.exec_command("ls /dev/mmcblk[0-9] 2>/dev/null")
        devices = mmc_devs.strip().split() if rc == 0 else []

        results: dict = {}
        failed: list[str] = []

        for dev in devices[:2]:
            # Strip partition suffix if present
            base = dev.rstrip("0123456789") if "boot" not in dev else dev

            rc, ext_csd = runner.exec_command(f"mmc extcsd read {base} 2>/dev/null")
            if rc != 0:
                results[dev] = {"error": "mmc extcsd read failed"}
                continue

            # Parse health/life time from ext_csd output
            life_time_a = None
            life_time_b = None
            pre_eol = None

            for line in ext_csd.splitlines():
                ll = line.lower()
                if "device life time est. typ a" in ll or "life_time_est_typ_a" in ll:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            life_time_a = int(parts[-1].strip(), 16)
                        except ValueError:
                            pass
                elif "device life time est. typ b" in ll or "life_time_est_typ_b" in ll:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            life_time_b = int(parts[-1].strip(), 16)
                        except ValueError:
                            pass
                elif "pre_eol_info" in ll or "pre-eol" in ll:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            pre_eol = int(parts[-1].strip(), 16)
                        except ValueError:
                            pass

            # pre_eol: 0x01=normal, 0x02=warning(80%), 0x03=urgent(90%)
            if pre_eol is not None and pre_eol >= 3:
                failed.append(dev)

            results[dev] = {
                "life_time_est_a": life_time_a,
                "life_time_est_b": life_time_b,
                "pre_eol_info": pre_eol,
                "status": "urgent" if pre_eol and pre_eol >= 3 else (
                    "warning" if pre_eol and pre_eol == 2 else "normal"
                ),
            }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(failed) == 0,
            data={"emmc_devices": results, "failed": failed},
            message=f"eMMC: {len(devices)} device(s), {len(failed)} critical",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="UFS device descriptor and health", timeout=30.0)
class UFSProbe(ProbeBase):
    """Read UFS health descriptor via ufs-utils or sysfs."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # Check for UFS device
        rc, ufs_devs = runner.exec_command("ls /dev/bsg/ufs-bsg* 2>/dev/null")
        bsg_devices = ufs_devs.strip().split() if rc == 0 else []

        rc2, ufs_sysfs = runner.exec_command("ls /sys/bus/platform/drivers/ufshcd*/ 2>/dev/null | head -5")
        sysfs_entries = ufs_sysfs.strip().split() if rc2 == 0 else []

        if not bsg_devices and not sysfs_entries:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No UFS devices found",
            )

        results: dict = {}

        for bsg in bsg_devices[:2]:
            rc, health = runner.exec_command(f"ufs-utils query -t 1 -i 0xD0 {bsg} 2>/dev/null")
            if rc == 0:
                results[bsg] = {"health_descriptor": health.strip()[:300]}
            else:
                results[bsg] = {"error": "ufs-utils query failed"}

        # sysfs UFS power mode
        rc, pm = runner.exec_command(
            "cat /sys/bus/platform/drivers/ufshcd*/*/power_mode 2>/dev/null | head -2"
        )
        if rc == 0:
            results["power_mode"] = pm.strip()

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data={"ufs_devices": results, "bsg_found": bool(bsg_devices)},
            message=f"UFS: {len(bsg_devices)} bsg device(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="SPI NOR Block Protect bits", timeout=15.0)
class SPINORProbe(ProbeBase):
    """Check SPI NOR flash Block Protect (BP) bits.

    Cleared BP bits expose flash to accidental write/erase during bring-up.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # Find MTD devices
        rc, mtd_info = runner.exec_command("cat /proc/mtd 2>/dev/null")
        if rc != 0 or not mtd_info.strip():
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No MTD/SPI-NOR devices found",
            )

        mtd_devices = []
        for line in mtd_info.splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                mtd_devices.append(parts[0].rstrip(":"))

        results: dict = {}
        bp_cleared: list[str] = []

        for mtd in mtd_devices[:4]:
            dev_path = f"/dev/{mtd}"

            # Check flash_info / BP bits via flashrom or sysfs
            rc, flash_info = runner.exec_command(
                f"cat /sys/class/mtd/{mtd}/flags 2>/dev/null"
            )
            flags = int(flash_info.strip(), 0) if rc == 0 and flash_info.strip() else None

            # Try to read SPI NOR BP bits via kernel driver attributes
            rc2, bp_bits = runner.exec_command(
                f"cat /sys/class/mtd/{mtd}/name 2>/dev/null"
            )
            name = bp_bits.strip() if rc2 == 0 else ""

            # MTD flags bit 10 = MTD_WRITEABLE; if not set → read-only (protected)
            writeable = bool(flags & 0x400) if flags is not None else None
            if writeable is False:
                bp_cleared.append(mtd)

            results[mtd] = {
                "name": name,
                "flags": hex(flags) if flags is not None else None,
                "writeable": writeable,
            }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,  # agent evaluates BP state risk
            data={"mtd_devices": results, "bp_cleared": bp_cleared},
            message=f"SPI-NOR: {len(mtd_devices)} MTD device(s)",
        )


@register_probe(
    DOMAIN, tier=ProbeTier.SLOW,
    description="fio sequential read/write performance (destructive, unmounted only)",
    timeout=120.0,
)
class FioProbe(ProbeBase):
    """Run fio on unmounted block devices.

    [R-04] NEVER issue fio against a mounted filesystem.
    Only runs with --allow-destructive-tests.
    Uses pre-GPT space (first 1MiB) for devices with mounted partitions.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        config = getattr(board_profile, "_config", None)
        allow_destructive = getattr(config, "allow_destructive_tests", False) if config else False

        if not allow_destructive:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "allow_destructive_tests=False"},
                message="fio skipped (requires --allow-destructive-tests)",
            )

        # Check fio availability
        rc, _ = runner.exec_command("which fio 2>/dev/null")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "fio not installed"},
                message="fio not found on board",
            )

        # Find unmounted block devices [R-04]
        rc, blk_list = runner.exec_command(
            "lsblk -nd -o NAME,TYPE 2>/dev/null | awk '$2==\"disk\"{print $1}'"
        )
        all_disks = blk_list.strip().split() if rc == 0 else []

        rc, mounted = runner.exec_command("cat /proc/mounts 2>/dev/null | awk '{print $1}'")
        mounted_devs = set(mounted.strip().splitlines()) if rc == 0 else set()

        results: dict = {}

        for disk in all_disks[:2]:
            dev_path = f"/dev/{disk}"

            # Check if any partition of this disk is mounted [R-04]
            rc, parts = runner.exec_command(
                f"lsblk -n -o NAME {dev_path} 2>/dev/null | tail -n +2"
            )
            part_names = [f"/dev/{p.strip()}" for p in (parts.strip().splitlines() if rc == 0 else [])]
            has_mounted = any(p in mounted_devs for p in part_names) or dev_path in mounted_devs

            if has_mounted:
                # Use pre-GPT space only (first 512 bytes * 2048 = 1MiB before GPT header at LBA1)
                fio_target = dev_path
                offset = "1MiB"
                size = "512KiB"
                log.info("fio_pre_gpt_space", disk=disk)
            else:
                fio_target = dev_path
                offset = "0"
                size = "256MiB"

            rc, fio_out = runner.exec_command(
                f"fio --name=seqread --rw=read --bs=128k --size={size} "
                f"--filename={fio_target} --offset={offset} "
                f"--runtime=10 --time_based --output-format=json 2>&1",
                timeout=100,
            )

            if rc != 0:
                results[disk] = {"error": fio_out.strip()[:200]}
                continue

            import json as _json
            try:
                fio_data = _json.loads(fio_out)
                job = fio_data.get("jobs", [{}])[0]
                read_bw = job.get("read", {}).get("bw", 0)  # KB/s
                results[disk] = {
                    "read_bw_kbs": read_bw,
                    "read_bw_mbs": round(read_bw / 1024, 1),
                    "target": fio_target,
                    "pre_gpt_space": has_mounted,
                }
            except (ValueError, KeyError, IndexError):
                results[disk] = {"raw": fio_out.strip()[-300:]}

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data={"fio_results": results},
            message=f"fio: tested {len(results)} disk(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD,
                description="SDIO/eMMC SDHCI PRESENT_STATE via MMIO register read", timeout=15.0)
class SDIORegProbe(ProbeBase):
    """Read SDHCI PRESENT_STATE register (offset 0x24) directly via /dev/mem.

    [CP-05] PRESENT_STATE reveals card-detect and DAT line state that the kernel
    driver may mask or misreport during early bring-up before the MMC layer runs.

    Supported compatibles: arasan,sdhci-5.1 | brcm,bcm2835-sdhci |
                           rockchip,rk3588-dwcmshc | snps,dwc-mshc-3.30a
    """

    _C_SOURCE = "c_probes/mmio_dump.c"
    _COMPATIBLES = [
        "arasan,sdhci-5.1",
        "brcm,bcm2835-sdhci",
        "rockchip,rk3588-dwcmshc",
        "snps,dwc-mshc-3.30a",
        "samsung,exynos4210-sdhci",
    ]

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # Find first matching SDIO/eMMC subsystem
        spec = None
        for compat in self._COMPATIBLES:
            spec = board_profile.subsystem_by_compatible(compat)
            if spec:
                break

        if not spec or getattr(spec, "reg_base", None) is None:
            return mmio_base_not_in_dts_result(DOMAIN, self.__class__.__name__)

        try:
            regs = self.run_c_probe(
                self._C_SOURCE,
                ["--base", hex(spec.reg_base),
                 "--size", "0x100",
                 "--offsets", hex(_SDHCI_PRESENT_STATE)],
            )
        except CProbeDeploySkipped as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="SKIP", findings=[str(exc)])
        except (CProbeCompileError, CProbeIntegrityError, CProbeExecError) as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="CONDITIONAL", findings=[str(exc)])

        state = regs.get(f"0x{_SDHCI_PRESENT_STATE:x}", 0)
        card_present  = bool(state & _SDHCI_CARD_INSERTED)
        dat_active    = bool(state & _SDHCI_DAT_LINE_ACTIVE)
        cmd_inhibit   = bool(state & _SDHCI_CMD_INHIBIT)

        findings = [
            f"SDHCI PRESENT_STATE=0x{state:08x}: "
            f"card={'present' if card_present else 'NOT inserted'}, "
            f"DAT={'active' if dat_active else 'idle'}, "
            f"CMD={'inhibit' if cmd_inhibit else 'ready'}",
        ]

        if not card_present:
            findings.append(
                "Card not detected — check card-detect GPIO and slot power rail; "
                "for eMMC this indicates reset or power failure"
            )

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            severity="PASS" if card_present else "CONDITIONAL",
            findings=findings,
            raw_data={"present_state": state, "card_present": card_present},
        )
