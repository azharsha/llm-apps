"""Power & Clocking domain probe implementations.

[PRD §4.1] These probes are invoked by the domain LLM agent via
exec_command/read_file tool calls dispatched through ProbeRunner.
The @register_probe decorator registers them for auto-discovery.

Key PRD constraints:
- [O-01] expected_mv lower bound 100mV (modern SoCs: Qualcomm VDD_MX=352mV)
- [CG-01] Rail Sanity Barrier: PMBus > hwmon > regulator sysfs priority
- [CG-04] Report failed_clocks list for cascade resolver
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "power_clocking"


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="Rail voltage via hwmon sysfs", timeout=15.0)
class RailVoltageProbe(ProbeBase):
    """Read rail voltages from hwmon sysfs.

    Priority: hwmon in*_input (µV → mV) → regulator sysfs.
    Lower bound [O-01]: expected_mv >= 100mV.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rails = getattr(board_profile, "rails", [])
        results: dict[str, Any] = {}
        failed: list[str] = []

        # Discover hwmon devices
        hwmon_rc, hwmon_dirs = runner.exec_command("ls /sys/class/hwmon/")
        hwmon_list = hwmon_dirs.strip().split() if hwmon_rc == 0 else []

        for rail in rails:
            name = getattr(rail, "name", "")
            expected_mv = getattr(rail, "expected_mv", 0)
            tolerance_pct = getattr(rail, "tolerance_pct", 5.0)
            # [O-01] clamp lower bound
            if expected_mv > 0 and expected_mv < 100:
                expected_mv = 100

            measured_mv: int | None = None

            # Try hwmon in*_input (µV)
            for hwmon in hwmon_list:
                base = f"/sys/class/hwmon/{hwmon}"
                rc, label_out = runner.exec_command(
                    f"grep -rl '{name}' {base}/ 2>/dev/null | head -1"
                )
                if rc == 0 and label_out.strip():
                    # Find corresponding in*_input
                    label_file = label_out.strip()
                    in_file = label_file.replace("_label", "_input")
                    rc2, val = runner.exec_command(f"cat {in_file} 2>/dev/null")
                    if rc2 == 0 and val.strip().isdigit():
                        measured_mv = int(val.strip()) // 1000
                        break

            # Fallback: regulator sysfs
            if measured_mv is None:
                rc, reg_out = runner.exec_command(
                    f"cat /sys/class/regulator/*/name 2>/dev/null | grep -i '{name}' | head -1"
                )
                if rc == 0 and reg_out.strip():
                    # Find matching regulator dir
                    rc2, reg_val = runner.exec_command(
                        f"grep -rl '{name}' /sys/class/regulator/*/name 2>/dev/null | "
                        f"head -1 | xargs dirname | xargs -I{{}} cat {{}}/microvolts 2>/dev/null"
                    )
                    if rc2 == 0 and reg_val.strip().isdigit():
                        measured_mv = int(reg_val.strip()) // 1000

            # Evaluate
            if measured_mv is None:
                results[name] = {"status": "unavailable", "expected_mv": expected_mv}
                continue

            if expected_mv > 0:
                delta_pct = abs(measured_mv - expected_mv) / expected_mv * 100
                ok = delta_pct <= tolerance_pct
                status = "ok" if ok else "out_of_tolerance"
                if not ok:
                    failed.append(name)
            else:
                status = "measured"

            results[name] = {
                "status": status,
                "measured_mv": measured_mv,
                "expected_mv": expected_mv,
                "tolerance_pct": tolerance_pct,
            }

        passed = len(failed) == 0
        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=passed,
            data={"rail_voltages": results, "failed_rails": failed},
            message=f"{len(failed)} rail(s) out of tolerance" if failed else "All rails within tolerance",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="PMBus voltage/current/power", timeout=30.0)
class PMBusProbe(ProbeBase):
    """Read PMBus devices via i2cget.

    [CG-01] PMBus has highest priority in rail reading.
    Reads READ_VOUT (0x8B), READ_IOUT (0x8C), READ_POUT (0x96).
    """

    # PMBus command codes
    _READ_VOUT = 0x8B
    _READ_IOUT = 0x8C
    _READ_POUT = 0x96

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rails = getattr(board_profile, "rails", [])
        results: dict[str, Any] = {}
        failed: list[str] = []

        # Check i2cget availability
        rc, _ = runner.exec_command("which i2cget 2>/dev/null")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "i2cget not available"},
                message="PMBus probe skipped: i2cget not found",
            )

        for rail in rails:
            name = getattr(rail, "name", "")
            pmbus_addr = getattr(rail, "pmbus_addr", None)
            pmbus_bus = getattr(rail, "pmbus_bus", None)
            expected_mv = getattr(rail, "expected_mv", 0)
            tolerance_pct = getattr(rail, "tolerance_pct", 5.0)

            if not pmbus_addr or pmbus_bus is None:
                continue

            # Read VOUT (LINEAR11 or ULINEAR16 format — raw word)
            rc, vout_raw = runner.exec_command(
                f"i2cget -y {pmbus_bus} {pmbus_addr} {self._READ_VOUT:#x} w 2>/dev/null"
            )
            if rc != 0 or not vout_raw.strip():
                results[name] = {"status": "i2c_error", "bus": pmbus_bus, "addr": pmbus_addr}
                failed.append(name)
                continue

            try:
                raw_word = int(vout_raw.strip(), 16)
                # Assume LINEAR16: Vout = raw * 2^N (N from VOUT_MODE)
                # Simplified: treat as mV directly (board-specific scaling)
                measured_mv = raw_word  # domain agent refines with VOUT_MODE
            except ValueError:
                results[name] = {"status": "parse_error", "raw": vout_raw.strip()}
                failed.append(name)
                continue

            if expected_mv > 0 and expected_mv >= 100:
                delta_pct = abs(measured_mv - expected_mv) / expected_mv * 100
                ok = delta_pct <= tolerance_pct
                status = "ok" if ok else "out_of_tolerance"
                if not ok:
                    failed.append(name)
            else:
                status = "measured"

            results[name] = {
                "status": status,
                "measured_mv": measured_mv,
                "expected_mv": expected_mv,
                "raw_word": vout_raw.strip(),
                "pmbus_bus": pmbus_bus,
                "pmbus_addr": pmbus_addr,
            }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(failed) == 0,
            data={"pmbus_rails": results, "failed": failed},
            message=f"PMBus: {len(results)} rails read, {len(failed)} failed",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="Clock/PLL status from debugfs", timeout=30.0)
class ClockProbe(ProbeBase):
    """Read clock enable/rate from debugfs clk tree.

    [CG-04] Reports failed_clocks list for cascade resolver.
    Reads /sys/kernel/debug/clk/*/clk_enable_count and clk_rate.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        clocks = getattr(board_profile, "clocks", [])
        results: dict[str, Any] = {}
        failed_clocks: list[str] = []

        # Check debugfs
        rc, _ = runner.exec_command("ls /sys/kernel/debug/clk/ 2>/dev/null | head -1")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "debugfs clk not available"},
                message="Clock probe skipped: debugfs not accessible",
            )

        # Enumerate all clocks if board_profile has none specified
        if not clocks:
            rc, clk_list = runner.exec_command("ls /sys/kernel/debug/clk/ 2>/dev/null")
            clock_names = clk_list.strip().split() if rc == 0 else []
        else:
            clock_names = [getattr(c, "name", "") for c in clocks]

        for clk_name in clock_names[:50]:  # cap at 50 to avoid runaway
            if not clk_name:
                continue

            base = f"/sys/kernel/debug/clk/{clk_name}"
            rc_en, en_val = runner.exec_command(f"cat {base}/clk_enable_count 2>/dev/null")
            rc_rate, rate_val = runner.exec_command(f"cat {base}/clk_rate 2>/dev/null")

            enable_count = int(en_val.strip()) if rc_en == 0 and en_val.strip().isdigit() else None
            rate_hz = int(rate_val.strip()) if rc_rate == 0 and rate_val.strip().isdigit() else None

            # Determine if clock should be enabled (from board profile or heuristic)
            required = False
            for c in clocks:
                if getattr(c, "name", "") == clk_name:
                    required = getattr(c, "required", False)
                    break

            status = "ok"
            if required and (enable_count is None or enable_count == 0):
                status = "disabled"
                failed_clocks.append(clk_name)
            elif rate_hz == 0 and enable_count and enable_count > 0:
                status = "rate_zero"
                failed_clocks.append(clk_name)

            results[clk_name] = {
                "status": status,
                "enable_count": enable_count,
                "rate_hz": rate_hz,
            }

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(failed_clocks) == 0,
            data={"clocks": results, "failed_clocks": failed_clocks},
            message=(
                f"{len(failed_clocks)} clock(s) failed" if failed_clocks
                else f"{len(results)} clocks checked, all OK"
            ),
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="Reset cause from last_boot_reason", timeout=10.0)
class ResetCauseProbe(ProbeBase):
    """Read reset/reboot cause.

    Checks: /sys/firmware/efi/efivars/ResetCause*, pstore, dmesg reboot reason.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        causes: list[str] = []

        # EFI variable
        rc, efi_out = runner.exec_command(
            "ls /sys/firmware/efi/efivars/ 2>/dev/null | grep -i reset | head -3"
        )
        if rc == 0 and efi_out.strip():
            causes.append(f"efi_reset_var: {efi_out.strip()}")

        # dmesg reset cause
        rc, dmesg_out = runner.exec_command(
            "dmesg 2>/dev/null | grep -i 'reboot\\|reset cause\\|last_reset\\|warm_boot' | head -5"
        )
        if rc == 0 and dmesg_out.strip():
            causes.append(f"dmesg: {dmesg_out.strip()[:300]}")

        # /proc/sys/kernel/panic (0=no panic reboot, >0=panic timeout)
        rc, panic_val = runner.exec_command("cat /proc/sys/kernel/panic 2>/dev/null")
        if rc == 0:
            causes.append(f"kernel_panic_timeout: {panic_val.strip()}")

        # ARM64: /sys/devices/platform/*/reset_reason
        rc, arm_reset = runner.exec_command(
            "cat /sys/devices/platform/*/reset_reason 2>/dev/null | head -3"
        )
        if rc == 0 and arm_reset.strip():
            causes.append(f"platform_reset_reason: {arm_reset.strip()}")

        unexpected = any(
            kw in " ".join(causes).lower()
            for kw in ("watchdog", "panic", "thermal", "hardware_fault")
        )

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=not unexpected,
            data={"reset_causes": causes, "unexpected_reset": unexpected},
            message=(
                "Unexpected reset cause detected" if unexpected
                else f"Reset cause: {causes[0][:100] if causes else 'unknown'}"
            ),
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="PSCI CPU on/offline state", timeout=15.0)
class PSCIProbe(ProbeBase):
    """Check PSCI CPU state via /sys/devices/system/cpu/cpu*/online.

    Also reads /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # CPU online counts
        rc, nproc = runner.exec_command("nproc 2>/dev/null || cat /sys/devices/system/cpu/online")
        online_cpus = nproc.strip() if rc == 0 else "unknown"

        rc, possible = runner.exec_command(
            "cat /sys/devices/system/cpu/possible 2>/dev/null"
        )
        possible_cpus = possible.strip() if rc == 0 else "unknown"

        # Check each CPU online file
        rc, cpu_dirs = runner.exec_command("ls /sys/devices/system/cpu/ | grep '^cpu[0-9]'")
        offline: list[str] = []
        if rc == 0:
            for cpu in cpu_dirs.strip().split():
                rc2, on_val = runner.exec_command(
                    f"cat /sys/devices/system/cpu/{cpu}/online 2>/dev/null"
                )
                if rc2 == 0 and on_val.strip() == "0":
                    offline.append(cpu)

        # cpufreq current
        rc, freq_out = runner.exec_command(
            "cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq 2>/dev/null | head -4"
        )
        freqs = [int(f) for f in freq_out.strip().split() if f.isdigit()] if rc == 0 else []

        # PSCI version
        rc, psci_ver = runner.exec_command(
            "cat /sys/firmware/devicetree/base/psci/method 2>/dev/null || "
            "dmesg 2>/dev/null | grep -i psci | head -2"
        )
        psci_info = psci_ver.strip()[:200] if rc == 0 else "unavailable"

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,  # agent evaluates PSCI failures
            data={
                "online_cpus": online_cpus,
                "possible_cpus": possible_cpus,
                "offline_cpus": offline,
                "current_freqs_khz": freqs,
                "psci_info": psci_info,
            },
            message=f"CPUs: {online_cpus} online, {len(offline)} offline",
        )
