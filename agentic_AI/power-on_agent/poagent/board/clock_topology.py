"""Platform-specific clock parent-child topology database.

[U-02] Specifies a stable API contract. All platform implementations must
conform to get_clock_topology() → ClockTopologyDB | None.

Qualcomm GCC, NXP CCM, Rockchip CRU, TI PRCM platform topologies are
encoded here. Unknown SoCs return None → CLOCK_TOPOLOGY_UNKNOWN warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# [LAST-S5] Canonical domain names — must match DomainResult.domain values exactly.
# Used by validate_clock_topology_consumers() at Phase 0.
KNOWN_DOMAINS: frozenset[str] = frozenset({
    "power_clocking",
    "compute_memory",
    "storage",
    "highspeed_serial",
    "display_graphics",
    "networking",
    "audio",
    "lowspeed_interface",
    "security_crypto",
    "sensors_misc",
})


@dataclass
class ClockEntry:
    """A single clock node in the platform topology DB.

    parent:    parent clock name (None = root oscillator)
    consumers: subsystem domain names that depend on this clock.
               MUST match DomainResult.domain values exactly.
               Common error: "high_speed_serial" vs "highspeed_serial".
    """
    parent: str | None
    consumers: list[str] = field(default_factory=list)


@dataclass
class ClockTopologyDB:
    """Platform-specific static clock topology database."""
    soc_compatible: str                  # e.g. "qcom,sc8280x"
    clocks: dict[str, ClockEntry]        # clock_name → ClockEntry


# ── Qualcomm GCC (SC8280X / SM8450 representative entries) ───────────────

_QCOM_SC8280X = ClockTopologyDB(
    soc_compatible="qcom,sc8280x",
    clocks={
        "ufs_phy_pll": ClockEntry(parent=None, consumers=["storage"]),
        "gcc_ufs_phy_phy_aux_clk": ClockEntry(
            parent="ufs_phy_pll",
            consumers=["storage"],
        ),
        "gcc_usb3_prim_phy_pipe_clk": ClockEntry(
            parent="gcc_ufs_phy_phy_aux_clk",
            consumers=["highspeed_serial"],
        ),
        "gcc_pcie0_pipe_clk": ClockEntry(
            parent="pcie_phy_pll",
            consumers=["highspeed_serial"],
        ),
        "gcc_pcie1_pipe_clk": ClockEntry(
            parent="pcie_phy_pll",
            consumers=["highspeed_serial"],
        ),
        "pcie_phy_pll": ClockEntry(parent=None, consumers=["highspeed_serial"]),
        "gcc_qupv3_i2c0_clk": ClockEntry(
            parent="gcc_qupv3_i2c0_clk_src",
            consumers=["lowspeed_interface"],
        ),
        "gcc_qupv3_i2c0_clk_src": ClockEntry(parent=None, consumers=["lowspeed_interface"]),
        "gcc_disp_gpll0_clk_src": ClockEntry(parent=None, consumers=["display_graphics"]),
        "gcc_dp_aux_clk": ClockEntry(
            parent="gcc_disp_gpll0_clk_src",
            consumers=["display_graphics"],
        ),
    },
)

_QCOM_SDM865 = ClockTopologyDB(
    soc_compatible="qcom,sdm865",
    clocks={
        "ufs_phy_pll": ClockEntry(parent=None, consumers=["storage"]),
        "gcc_ufs_phy_phy_aux_clk": ClockEntry(
            parent="ufs_phy_pll",
            consumers=["storage"],
        ),
        "gcc_usb3_prim_phy_pipe_clk": ClockEntry(
            parent="gcc_ufs_phy_phy_aux_clk",
            consumers=["highspeed_serial"],
        ),
        "gcc_pcie0_pipe_clk": ClockEntry(
            parent="pcie_phy_pll",
            consumers=["highspeed_serial"],
        ),
        "pcie_phy_pll": ClockEntry(parent=None, consumers=["highspeed_serial"]),
    },
)

# ── NXP i.MX8M CCM (representative entries) ──────────────────────────────

_NXP_IMX8MM = ClockTopologyDB(
    soc_compatible="fsl,imx8mm",
    clocks={
        "sys_pll1": ClockEntry(parent=None, consumers=["compute_memory"]),
        "sys_pll2": ClockEntry(parent=None, consumers=["storage", "networking"]),
        "imx8mm_clk_enet_ref": ClockEntry(
            parent="sys_pll2",
            consumers=["networking"],
        ),
        "imx8mm_clk_usb_core": ClockEntry(
            parent="sys_pll1",
            consumers=["highspeed_serial"],
        ),
        "imx8mm_clk_pcie1_phy": ClockEntry(
            parent="sys_pll2",
            consumers=["highspeed_serial"],
        ),
        "imx8mm_clk_sai1": ClockEntry(
            parent="sys_pll1",
            consumers=["audio"],
        ),
    },
)

_NXP_IMX95 = ClockTopologyDB(
    soc_compatible="fsl,imx95",
    clocks={
        "sys_pll1": ClockEntry(parent=None, consumers=["compute_memory"]),
        "sys_pll2": ClockEntry(parent=None, consumers=["storage", "networking"]),
        "imx95_clk_enet": ClockEntry(parent="sys_pll2", consumers=["networking"]),
    },
)

# ── Rockchip RK3588 CRU ───────────────────────────────────────────────────

_ROCKCHIP_RK3588 = ClockTopologyDB(
    soc_compatible="rockchip,rk3588",
    clocks={
        "gpll": ClockEntry(parent=None, consumers=["compute_memory", "storage"]),
        "cpll": ClockEntry(parent=None, consumers=["display_graphics", "audio"]),
        "aclk_pcie0": ClockEntry(parent="gpll", consumers=["highspeed_serial"]),
        "aclk_pcie1": ClockEntry(parent="gpll", consumers=["highspeed_serial"]),
        "aclk_usb3": ClockEntry(parent="gpll", consumers=["highspeed_serial"]),
        "clk_sai0": ClockEntry(parent="cpll", consumers=["audio"]),
    },
)

# ── TI K3 (AM6x / J7x) PRCM ──────────────────────────────────────────────

_TI_K3_AM64 = ClockTopologyDB(
    soc_compatible="ti,am642",
    clocks={
        "main_pll0": ClockEntry(parent=None, consumers=["compute_memory"]),
        "main_usb0_ref": ClockEntry(parent="main_pll0", consumers=["highspeed_serial"]),
        "main_pcie0_refclk": ClockEntry(parent=None, consumers=["highspeed_serial"]),
        "main_mcan0_ref": ClockEntry(parent="main_pll0", consumers=["networking"]),
    },
)

# ── Platform DB index ─────────────────────────────────────────────────────

_TOPOLOGY_DB: dict[str, ClockTopologyDB] = {
    "qcom,sc8280x": _QCOM_SC8280X,
    "qcom,sdm865": _QCOM_SDM865,
    "fsl,imx8mm": _NXP_IMX8MM,
    "fsl,imx95": _NXP_IMX95,
    "rockchip,rk3588": _ROCKCHIP_RK3588,
    "ti,am642": _TI_K3_AM64,
}


def get_clock_topology(soc_compatible: str) -> ClockTopologyDB | None:
    """Return ClockTopologyDB for the given root DTS compatible string.

    Returns None if the SoC is not in the static DB.
    Orchestrator emits CLOCK_TOPOLOGY_UNKNOWN on None return.
    """
    return _TOPOLOGY_DB.get(soc_compatible)


def validate_clock_topology_consumers(clock_dependency_map: dict) -> list[str]:
    """[LAST-S5] Validate all consumer domain names against KNOWN_DOMAINS.

    Called at Phase 0 after clock_dependency_map is built from DTS +
    debugfs + platform DB.

    Returns a list of warning strings (CLOCK_TOPOLOGY_CONSUMER_UNKNOWN).
    Does not abort — topology DB is informational; cascade resolution
    falls back to DTS phandles.

    Common error: "high_speed_serial" (with underscore) instead of
    "highspeed_serial" (no separator). This causes the cascade resolver
    to silently skip all USB3/PCIe failures.
    """
    warnings: list[str] = []
    for clock_name, entry in clock_dependency_map.items():
        for consumer in entry.get("consumers", []):
            if consumer not in KNOWN_DOMAINS:
                warnings.append(
                    f"CLOCK_TOPOLOGY_CONSUMER_UNKNOWN: clock '{clock_name}' "
                    f"references unknown domain '{consumer}'. "
                    f"Cascade resolution will silently skip this domain. "
                    f"Valid domains: {sorted(KNOWN_DOMAINS)}"
                )
    return warnings
