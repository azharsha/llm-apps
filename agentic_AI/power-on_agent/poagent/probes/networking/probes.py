"""Networking domain probe implementations.

Key PRD constraints:
- [N-SG-10] PHY MII dump via mii-tool or ethtool --dump-module-eeprom.
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "networking"


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="Ethernet MAC/PHY link and MII dump", timeout=30.0)
class EthernetProbe(ProbeBase):
    """Check Ethernet interface state, MAC, and PHY via ethtool/mii-tool [N-SG-10]."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # Enumerate interfaces
        rc, ifaces = runner.exec_command(
            "ls /sys/class/net/ 2>/dev/null | grep -vE '^(lo|docker|virbr|veth|dummy)'"
        )
        interfaces = ifaces.strip().split() if rc == 0 else []
        data["interfaces"] = interfaces

        iface_data: dict = {}
        for iface in interfaces[:4]:
            info: dict = {}

            # Carrier/operstate
            rc, carrier = runner.exec_command(f"cat /sys/class/net/{iface}/carrier 2>/dev/null")
            info["carrier"] = carrier.strip() if rc == 0 else "unknown"

            rc, operstate = runner.exec_command(f"cat /sys/class/net/{iface}/operstate 2>/dev/null")
            info["operstate"] = operstate.strip() if rc == 0 else "unknown"

            rc, speed = runner.exec_command(f"cat /sys/class/net/{iface}/speed 2>/dev/null")
            info["speed_mbps"] = int(speed.strip()) if rc == 0 and speed.strip().lstrip("-").isdigit() else None

            # ethtool for PHY/driver info
            rc, ethtool = runner.exec_command(f"ethtool {iface} 2>/dev/null")
            if rc == 0:
                for line in ethtool.splitlines():
                    if "Speed:" in line:
                        info["ethtool_speed"] = line.strip()
                    elif "Link detected:" in line:
                        info["link_detected"] = "yes" in line.lower()
                    elif "Duplex:" in line:
                        info["duplex"] = line.strip()

            # ethtool -i for driver
            rc, drv = runner.exec_command(f"ethtool -i {iface} 2>/dev/null | head -5")
            if rc == 0:
                info["driver"] = drv.strip()[:100]

            # MII dump [N-SG-10]
            rc, mii = runner.exec_command(f"mii-tool -v {iface} 2>/dev/null")
            if rc == 0 and mii.strip():
                info["mii_dump"] = mii.strip()[:200]

            # ethtool statistics
            rc, stats = runner.exec_command(f"ethtool -S {iface} 2>/dev/null | grep -iE 'error|drop|miss' | head -10")
            if rc == 0 and stats.strip():
                info["error_stats"] = stats.strip().splitlines()[:5]

            iface_data[iface] = info

        data["interface_details"] = iface_data

        # dmesg NIC errors
        rc, nic_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'eth.*error|phy.*fail|link.*fail|mac.*err' | tail -5"
        )
        if rc == 0 and nic_err.strip():
            data["nic_dmesg_errors"] = nic_err.strip().splitlines()[:5]

        linked = [i for i, d in iface_data.items() if d.get("carrier") == "1"]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"Ethernet: {len(interfaces)} interface(s), {len(linked)} with carrier",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="Wi-Fi adapter status and scan", timeout=30.0)
class WiFiProbe(ProbeBase):
    """Check Wi-Fi adapter via iwconfig/iw and regulatory domain."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # iw list for physical devices
        rc, iw_list = runner.exec_command("iw list 2>/dev/null | grep -E 'Wiphy|Band|Capabilities' | head -20")
        if rc == 0 and iw_list.strip():
            data["iw_list"] = iw_list.strip()[:300]

        # Wi-Fi interfaces
        rc, wifi_ifaces = runner.exec_command(
            "iw dev 2>/dev/null | grep Interface | awk '{print $2}'"
        )
        wifi_list = wifi_ifaces.strip().split() if rc == 0 else []
        data["wifi_interfaces"] = wifi_list

        for wlan in wifi_list[:2]:
            rc, link = runner.exec_command(f"iw {wlan} link 2>/dev/null")
            if rc == 0:
                data[f"{wlan}_link"] = link.strip()[:200]

        # Regulatory domain
        rc, regdom = runner.exec_command("iw reg get 2>/dev/null | head -5")
        if rc == 0:
            data["regulatory_domain"] = regdom.strip()[:100]

        # rfkill status
        rc, rfkill = runner.exec_command("rfkill list 2>/dev/null")
        if rc == 0:
            data["rfkill"] = rfkill.strip()[:200]

        # dmesg Wi-Fi errors
        rc, wifi_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'wifi|wlan|cfg80211.*error|firmware.*load.*fail' | tail -5"
        )
        if rc == 0 and wifi_err.strip():
            data["wifi_dmesg"] = wifi_err.strip().splitlines()[:5]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"Wi-Fi: {len(wifi_list)} interface(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="Bluetooth adapter state", timeout=20.0)
class BluetoothProbe(ProbeBase):
    """Check Bluetooth adapter state via hciconfig/btmgmt."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # hciconfig
        rc, hciconfig = runner.exec_command("hciconfig -a 2>/dev/null")
        if rc == 0 and hciconfig.strip():
            data["hciconfig"] = hciconfig.strip()[:400]
            hci_devs = [l.split(":")[0] for l in hciconfig.splitlines() if l.startswith("hci")]
            data["hci_devices"] = hci_devs
        else:
            # btmgmt as fallback
            rc, btmgmt = runner.exec_command("btmgmt info 2>/dev/null | head -15")
            if rc == 0:
                data["btmgmt"] = btmgmt.strip()[:200]
            data["hci_devices"] = []

        # BT firmware dmesg
        rc, bt_fw = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'bluetooth|hci.*firmware|btusb|brcm' | tail -5"
        )
        if rc == 0 and bt_fw.strip():
            data["bt_dmesg"] = bt_fw.strip().splitlines()[:5]

        errors = [m for m in data.get("bt_dmesg", []) if any(
            w in m.lower() for w in ("error", "fail", "timeout")
        )]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(errors) == 0,
            data=data,
            message=f"Bluetooth: {len(data.get('hci_devices', []))} adapter(s)",
        )
