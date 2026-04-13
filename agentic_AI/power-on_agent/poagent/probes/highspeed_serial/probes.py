"""High-Speed Serial domain probe implementations.

Key PRD constraints:
- [FINAL-C3] setpci ONLY on endpoint devices (class != 0x0604 bridge).
- [O-04] PCIe AER baseline at Phase 0; delta reported by agent.
- [SG-02] USB-C PD: ucsi_acpi / typec sysfs.
- [SG-03] IOMMU binding check per PCIe device.
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

DOMAIN = "highspeed_serial"

# PCIe LTSSM state machine values (DesignWare / standard PCIe)
_LTSSM_STATES: dict[int, str] = {
    0x00: "DETECT_QUIET",
    0x01: "DETECT_ACT",
    0x02: "POLLING_ACTIVE",
    0x03: "POLLING_COMPLIANCE",
    0x04: "POLLING_CONFIG",
    0x08: "L0",           # Some SoCs use 0x08 for L0
    0x10: "L0",
    0x11: "L0S",
    0x14: "L1_IDLE",
    0x15: "L1_PHY_SLEEP",
    0x20: "RECOVERY_RCVR_LOCK",
    0x21: "RECOVERY_SPEED",
    0x22: "RECOVERY_RCVR_CFG",
    0x23: "RECOVERY_IDLE",
    0x30: "HOT_RESET",
    0x32: "LOOPBACK_ACTIVE",
    0x34: "DISABLED",
}

# PCIe LTSSM register offsets by compatible string
_PCIE_LTSSM_OFFSETS: dict[str, int] = {
    "rockchip,rk3588-pcie":    0x5C,
    "qcom,pcie-sc8280xp":      0x1B4,
    "fsl,imx8mp-pcie":         0x80,
    "snps,dw-pcie":            0x5C,   # generic DesignWare fallback
    "brcm,iproc-pcie":         0x0C00,
    "ti,j721e-pcie-host":      0x38,
}

# DWC3 register offsets
_DWC3_GSTS_OFFSET    = 0xC118
_DWC3_CLKNDGS_BIT   = 30    # 1 = clock NOT gated (running)


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="PCIe AER error counters", timeout=30.0)
class PCIeAERProbe(ProbeBase):
    """Read PCIe AER correctable/uncorrectable error counters.

    [O-04] Baseline is read at Phase 0; agent computes delta.
    [FINAL-C3] setpci only on endpoints (class != PCI bridge 0x0604).
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # Discover PCIe devices
        rc, lspci = runner.exec_command("lspci -mm 2>/dev/null | head -50")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "lspci not available"},
                message="PCIe probe skipped: lspci not found",
            )

        devices: dict = {}

        # AER via sysfs (preferred over setpci — no driver conflict)
        rc, aer_dirs = runner.exec_command(
            "find /sys/bus/pci/devices/ -name 'aer_dev_correctable' 2>/dev/null | head -20"
        )
        aer_paths = aer_dirs.strip().splitlines() if rc == 0 else []

        for aer_path in aer_paths:
            pci_dev = aer_path.split("/")[-2] if "/" in aer_path else ""
            if not pci_dev:
                continue

            rc, ce_raw = runner.exec_command(f"cat {aer_path} 2>/dev/null")
            rc2, ue_path = runner.exec_command(
                f"cat {aer_path.replace('correctable', 'uncorrectable')} 2>/dev/null"
            )

            # Parse AER sysfs: "RxErr 0\nBadTLP 0\n..."
            ce_total = 0
            ue_total = 0
            if rc == 0:
                for line in ce_raw.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[1].isdigit():
                        ce_total += int(parts[1])
            if rc2 == 0:
                for line in ue_path.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[1].isdigit():
                        ue_total += int(parts[1])

            devices[pci_dev] = {
                "aer_ce_total": ce_total,
                "aer_ue_total": ue_total,
            }

        # PCIe link status via setpci — endpoints only [FINAL-C3]
        rc, pci_list = runner.exec_command(
            "lspci -D 2>/dev/null | grep -v ' PCI bridge' | awk '{print $1}' | head -20"
        )
        endpoints = pci_list.strip().splitlines() if rc == 0 else []

        link_statuses: dict = {}
        for ep in endpoints[:10]:
            ep = ep.strip()
            if not ep:
                continue
            # Read Link Status register (cap offset varies — use lspci -v)
            rc, link_cap = runner.exec_command(
                f"lspci -vvv -s {ep} 2>/dev/null | grep -A2 'LnkSta:' | head -3"
            )
            if rc == 0 and link_cap.strip():
                link_statuses[ep] = link_cap.strip()[:200]

        all_ue = sum(d.get("aer_ue_total", 0) for d in devices.values())

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=all_ue == 0,
            data={
                "pcie_devices": devices,
                "link_statuses": link_statuses,
                "total_aer_ue": all_ue,
                "total_aer_ce": sum(d.get("aer_ce_total", 0) for d in devices.values()),
            },
            message=f"PCIe: {len(devices)} device(s), UE={all_ue}",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="USB3 SuperSpeed link status", timeout=20.0)
class USB3Probe(ProbeBase):
    """Check USB3 SuperSpeed (5G/10G/20G) link state and error counters."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # USB3 host controllers
        rc, usb3_hc = runner.exec_command(
            "lspci 2>/dev/null | grep -i 'USB 3\\|xHCI'"
        )
        if rc == 0:
            data["usb3_controllers"] = usb3_hc.strip().splitlines()[:5]

        # USB3 devices via usbutils
        rc, lsusb = runner.exec_command("lsusb -t 2>/dev/null")
        if rc == 0:
            data["usb_topology"] = lsusb.strip()[:500]

        # SuperSpeed devices (speed=5000, 10000, 20000)
        rc, ss_devs = runner.exec_command(
            "grep -r '5000\\|10000\\|20000' /sys/bus/usb/devices/*/speed 2>/dev/null"
        )
        data["superspeed_devices"] = ss_devs.strip().splitlines()[:10] if rc == 0 else []

        # USB3 error counters via xhci debugfs
        rc, xhci_err = runner.exec_command(
            "cat /sys/kernel/debug/usb/xhci-hcd*/xhci-hcd*/xHCI_error_counts 2>/dev/null | head -20"
        )
        if rc == 0 and xhci_err.strip():
            data["xhci_errors"] = xhci_err.strip()[:300]

        # dmesg USB3 errors
        rc, dmesg_usb = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'usb.*error|xhci.*failed|usb.*reset' | tail -10"
        )
        if rc == 0 and dmesg_usb.strip():
            data["usb_dmesg_errors"] = dmesg_usb.strip().splitlines()[:5]

        has_errors = bool(data.get("usb_dmesg_errors"))

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=not has_errors,
            data=data,
            message=f"USB3: {len(data.get('superspeed_devices', []))} SuperSpeed device(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="Thunderbolt/USB4 link status", timeout=20.0)
class ThunderboltProbe(ProbeBase):
    """Check Thunderbolt/USB4 controller and device state."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        # TBT controller
        rc, tbt_ctrl = runner.exec_command(
            "lspci 2>/dev/null | grep -i 'thunderbolt\\|USB4'"
        )
        if rc != 0 or not tbt_ctrl.strip():
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No Thunderbolt/USB4 controller found",
            )

        data: dict = {"controllers": tbt_ctrl.strip().splitlines()[:3]}

        # TBT sysfs
        rc, tbt_devs = runner.exec_command(
            "ls /sys/bus/thunderbolt/devices/ 2>/dev/null"
        )
        if rc == 0:
            data["tbt_devices"] = tbt_devs.strip().split()[:10]

        # Security level
        rc, sec = runner.exec_command(
            "cat /sys/bus/thunderbolt/devices/*/security 2>/dev/null | head -3"
        )
        if rc == 0:
            data["security_levels"] = sec.strip().splitlines()[:3]

        # dmesg TBT
        rc, tbt_dmesg = runner.exec_command(
            "dmesg 2>/dev/null | grep -i 'thunderbolt\\|tbt' | tail -10"
        )
        if rc == 0:
            data["tbt_dmesg"] = tbt_dmesg.strip().splitlines()[:5]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"Thunderbolt: {len(data.get('tbt_devices', []))} device(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="USB-C Power Delivery via ucsi/typec sysfs", timeout=15.0)
class USBCPDProbe(ProbeBase):
    """Check USB-C Power Delivery state via ucsi_acpi / typec sysfs [SG-02]."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # UCSI / Type-C sysfs
        rc, typec_ports = runner.exec_command(
            "ls /sys/class/typec/ 2>/dev/null"
        )
        if rc != 0 or not typec_ports.strip():
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No USB-C Type-C ports found via sysfs",
            )

        ports = typec_ports.strip().split()
        data["ports"] = []

        for port in ports[:4]:
            base = f"/sys/class/typec/{port}"
            port_info: dict = {"name": port}

            rc, power_role = runner.exec_command(f"cat {base}/power_role 2>/dev/null")
            if rc == 0:
                port_info["power_role"] = power_role.strip()

            rc, data_role = runner.exec_command(f"cat {base}/data_role 2>/dev/null")
            if rc == 0:
                port_info["data_role"] = data_role.strip()

            rc, orientation = runner.exec_command(f"cat {base}/orientation 2>/dev/null")
            if rc == 0:
                port_info["orientation"] = orientation.strip()

            # PD contracts
            rc, pd_contract = runner.exec_command(
                f"cat {base}/partner/usb_power_delivery/*/active 2>/dev/null | head -3"
            )
            if rc == 0 and pd_contract.strip():
                port_info["pd_contract"] = pd_contract.strip()[:100]

            data["ports"].append(port_info)

        # ucsi_acpi PSY info
        rc, ucsi_psy = runner.exec_command(
            "cat /sys/class/power_supply/ucsi-source-psy*/online 2>/dev/null | head -2"
        )
        if rc == 0:
            data["ucsi_psy_online"] = ucsi_psy.strip()

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"USB-C PD: {len(data.get('ports', []))} port(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD,
                description="PCIe LTSSM link-training state via MMIO register read", timeout=15.0)
class PCIeLTSSMProbe(ProbeBase):
    """Read the PCIe LTSSM register directly via /dev/mem.

    [CP-05] The LTSSM state reveals exactly where link training stalled —
    sysfs only reports the final trained speed, not the failure state.

    Base address is taken from DTS pcie_slots[].reg_base — no user input required.
    """

    _C_SOURCE = "c_probes/mmio_dump.c"

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        pcie_slots = getattr(board_profile, "pcie_slots", [])
        if not pcie_slots:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                severity="SKIP",
                findings=["No PCIe slots declared in DTS"],
            )

        all_findings: list[str] = []
        overall_severity = "PASS"

        for slot in pcie_slots:
            reg_base = getattr(slot, "reg_base", None)
            if reg_base is None:
                all_findings.append(
                    f"SKIP slot {getattr(slot, 'node_path', '?')}: "
                    "no reg property in DTS"
                )
                continue

            compat_list = getattr(slot, "compatible", [])
            compat = compat_list[0] if compat_list else "snps,dw-pcie"
            ltssm_off = _PCIE_LTSSM_OFFSETS.get(compat, 0x5C)

            try:
                regs = self.run_c_probe(
                    self._C_SOURCE,
                    ["--base", hex(reg_base),
                     "--size", "0x200",
                     "--offsets", hex(ltssm_off)],
                )
            except CProbeDeploySkipped as exc:
                return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                                   severity="SKIP", findings=[str(exc)])
            except (CProbeCompileError, CProbeIntegrityError, CProbeExecError) as exc:
                all_findings.append(str(exc))
                if overall_severity == "PASS":
                    overall_severity = "CONDITIONAL"
                continue

            raw = regs.get(f"0x{ltssm_off:x}", 0)
            ltssm = raw & 0x3F
            state_name = _LTSSM_STATES.get(ltssm, f"UNKNOWN_0x{ltssm:02x}")
            link_up = ltssm in (0x08, 0x10)  # L0

            finding = (
                f"PCIe slot {getattr(slot, 'node_path', hex(reg_base))}: "
                f"LTSSM={state_name} (0x{ltssm:02x}) — "
                f"{'link trained (L0)' if link_up else 'link NOT in L0'}"
            )
            all_findings.append(finding)

            if not link_up:
                overall_severity = "FAIL" if ltssm < 0x10 else "CONDITIONAL"

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            severity=overall_severity,
            findings=all_findings,
            raw_data={"ltssm_raw": raw if pcie_slots else 0},
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD,
                description="USB DWC3 GSTS clock-gate and PHY power state via MMIO", timeout=15.0)
class USBDwc3Probe(ProbeBase):
    """Read DWC3 Global Status Register (GSTS) at offset 0xC118.

    [CP-05] GSTS bit 30 (CLKNDGS): 1 = clock running, 0 = clock gated.
    Clock-gated DWC3 means USB is non-functional regardless of what sysfs reports.

    Base address is taken from SubsystemSpec for compatible "snps,dwc3".
    """

    _C_SOURCE = "c_probes/mmio_dump.c"
    _COMPATIBLE = "snps,dwc3"

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        spec = board_profile.subsystem_by_compatible(self._COMPATIBLE)
        if not spec or getattr(spec, "reg_base", None) is None:
            return mmio_base_not_in_dts_result(DOMAIN, self.__class__.__name__)

        map_size = _DWC3_GSTS_OFFSET + 4

        try:
            regs = self.run_c_probe(
                self._C_SOURCE,
                ["--base", hex(spec.reg_base),
                 "--size", hex(map_size),
                 "--offsets", hex(_DWC3_GSTS_OFFSET)],
            )
        except CProbeDeploySkipped as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="SKIP", findings=[str(exc)])
        except (CProbeCompileError, CProbeIntegrityError, CProbeExecError) as exc:
            return ProbeResult(probe_name=self.__class__.__name__, domain=DOMAIN,
                               severity="CONDITIONAL", findings=[str(exc)])

        gsts = regs.get(f"0x{_DWC3_GSTS_OFFSET:x}", 0)
        clk_ok = bool((gsts >> _DWC3_CLKNDGS_BIT) & 1)

        findings = [
            f"DWC3 GSTS=0x{gsts:08x}: USB clock {'running' if clk_ok else 'GATED — USB non-functional'}"
        ]

        if not clk_ok:
            findings.append(
                "Check USB reference clock (CKREF_SEL) and power domain — "
                "DWC3 requires 20/24/48 MHz reference"
            )

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            severity="PASS" if clk_ok else "FAIL",
            findings=findings,
            raw_data={"gsts": gsts, "clk_running": clk_ok},
        )
