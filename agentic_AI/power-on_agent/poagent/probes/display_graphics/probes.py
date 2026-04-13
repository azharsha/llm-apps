"""Display & Graphics domain probe implementations."""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "display_graphics"


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="DRM/KMS connector and mode status", timeout=20.0)
class DRMProbe(ProbeBase):
    """Read DRM card/connector state from sysfs."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # DRM cards
        rc, cards = runner.exec_command("ls /sys/class/drm/ 2>/dev/null | grep '^card[0-9]$'")
        card_list = cards.strip().split() if rc == 0 else []
        data["drm_cards"] = card_list

        connectors: list[dict] = []
        for card in card_list[:2]:
            rc, conns = runner.exec_command(f"ls /sys/class/drm/{card}/ 2>/dev/null | grep -v '^version$'")
            for conn in (conns.strip().split() if rc == 0 else []):
                conn_path = f"/sys/class/drm/{card}/{conn}"
                rc2, status = runner.exec_command(f"cat {conn_path}/status 2>/dev/null")
                rc3, enabled = runner.exec_command(f"cat {conn_path}/enabled 2>/dev/null")
                connectors.append({
                    "name": conn,
                    "status": status.strip() if rc2 == 0 else "unknown",
                    "enabled": enabled.strip() if rc3 == 0 else "unknown",
                })

        data["connectors"] = connectors

        # dmesg DRM errors
        rc, drm_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'drm.*error|drm.*fail|gpu.*hang' | tail -5"
        )
        if rc == 0 and drm_err.strip():
            data["drm_errors"] = drm_err.strip().splitlines()[:5]

        # GPU driver
        rc, gpu_driver = runner.exec_command(
            "lspci 2>/dev/null | grep -iE 'vga|display|3d|gpu' | head -3"
        )
        if rc == 0:
            data["gpu_devices"] = gpu_driver.strip().splitlines()[:3]

        connected = [c for c in connectors if c.get("status") == "connected"]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"DRM: {len(card_list)} card(s), {len(connected)} connector(s) connected",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="HDMI/DP EDID read", timeout=20.0)
class EDIDProbe(ProbeBase):
    """Read EDID from HDMI/DP connectors."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        edid_results: dict = {}

        # EDID via drm sysfs
        rc, edid_paths = runner.exec_command(
            "find /sys/class/drm/ -name 'edid' 2>/dev/null | head -5"
        )
        for path in (edid_paths.strip().splitlines() if rc == 0 else []):
            path = path.strip()
            if not path:
                continue
            rc2, edid_hex = runner.exec_command(f"xxd {path} 2>/dev/null | head -10")
            conn_name = path.split("/")[-2] if "/" in path else path
            edid_results[conn_name] = {
                "edid_hex": edid_hex.strip()[:200] if rc2 == 0 else None,
                "has_edid": rc2 == 0 and bool(edid_hex.strip()),
            }

        # modetest alternative
        rc, modetest = runner.exec_command("modetest 2>/dev/null | grep -E 'HDMI|DP|connected' | head -10")
        if rc == 0 and modetest.strip():
            edid_results["modetest"] = modetest.strip()[:300]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data={"edid_connectors": edid_results},
            message=f"EDID: {len(edid_results)} connector(s) checked",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="MIPI DSI panel status", timeout=20.0)
class MIPIDSIProbe(ProbeBase):
    """Check MIPI DSI panel state via sysfs and dmesg."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # DSI via device tree / sysfs
        rc, dsi_devs = runner.exec_command(
            "find /sys/bus/platform/devices/ -name '*dsi*' 2>/dev/null | head -5"
        )
        data["dsi_devices"] = dsi_devs.strip().splitlines()[:5] if rc == 0 else []

        # dmesg MIPI DSI
        rc, dsi_dmesg = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'dsi|mipi|panel' | head -15"
        )
        if rc == 0 and dsi_dmesg.strip():
            data["dsi_dmesg"] = dsi_dmesg.strip().splitlines()[:10]

        # Panel backlight
        rc, bl = runner.exec_command(
            "cat /sys/class/backlight/*/bl_power 2>/dev/null | head -3"
        )
        if rc == 0:
            data["backlight_power"] = bl.strip()

        errors = [m for m in data.get("dsi_dmesg", []) if any(
            w in m.lower() for w in ("error", "fail", "timeout", "no panel")
        )]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(errors) == 0,
            data=data,
            message=f"MIPI DSI: {len(data.get('dsi_devices', []))} device(s), {len(errors)} error(s)",
        )
