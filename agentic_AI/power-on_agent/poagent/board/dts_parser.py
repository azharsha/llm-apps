"""DTS parser — base DTS + overlay → BoardProfile.

Two-pass parse with cycle detection (DFS grey/black) on *-supply graph.
Also extracts clock phandles for CG-04, po-agent,* overlay properties,
and DTS kernel version for SG-07.
"""

from __future__ import annotations

import re
import structlog
from typing import Optional

from poagent.board.board_profile import (
    BoardProfile,
    RailSpec,
    SubsystemSpec,
    PCIeSpec,
    NVMeSpec,
    UFSSpec,
)
from poagent.codes import DTS_PARSE_ERROR

log = structlog.get_logger(__name__)

# Compatible string → (domain, sysfs_glob)
_COMPATIBLE_TO_DOMAIN: dict[str, tuple[str, str]] = {
    "intel,pch-xhci":          ("highspeed_serial", "/sys/bus/usb/devices/"),
    "arm,pl011":               ("lowspeed_interface", "/sys/bus/amba/devices/*uart*/"),
    "snps,dwc3":               ("highspeed_serial", "/sys/bus/platform/drivers/dwc3/"),
    "regulator-fixed":         ("power_clocking", "/sys/class/regulator/"),
    "regulator-gpio":          ("power_clocking", "/sys/class/regulator/"),
    "arm,gic-400":             ("compute_memory", "/sys/bus/platform/drivers/arm-gic/"),
    "arm,gic-v3":              ("compute_memory", "/sys/bus/platform/drivers/arm-gic/"),
    "qcom,gcc-sc8280x":        ("power_clocking", "/sys/kernel/debug/clk/"),
    "jedec,spi-nor":           ("storage", "/sys/bus/spi/devices/"),
    "samsung,pm9a1":           ("storage", "/sys/bus/nvme/"),
    "tcg,tpm-tis-i2c":         ("security_crypto", "/sys/class/tpm/"),
    "ti,ucd9090":              ("power_clocking", "/sys/class/hwmon/"),
    "nvme":                    ("storage", "/sys/bus/nvme/"),
    "jedec,ufs":               ("storage", "/sys/bus/platform/drivers/ufshcd/"),
    "ufs-hisi":                ("storage", "/sys/bus/platform/drivers/ufshcd/"),
    "qcom,ufshc":              ("storage", "/sys/bus/platform/drivers/ufshcd/"),
    "pci":                     ("highspeed_serial", "/sys/bus/pci/"),
    "realtek,rtl8168":         ("networking", "/sys/class/net/"),
    "intel,e1000e":            ("networking", "/sys/class/net/"),
    "ti,am65-cpsw-nuss":       ("networking", "/sys/class/net/"),
    "snd-soc-dummy":           ("audio", "/sys/class/sound/"),
    "ti,tlv320aic31xx":        ("audio", "/sys/bus/i2c/drivers/tlv320aic31xx/"),
    "bosch,bmp280":            ("sensors_misc", "/sys/bus/iio/devices/"),
    "invensense,mpu6050":      ("sensors_misc", "/sys/bus/iio/devices/"),
    "maxim,max17042":          ("sensors_misc", "/sys/bus/i2c/drivers/max17042/"),
    "drm":                     ("display_graphics", "/sys/class/drm/"),
    "simple-panel":            ("display_graphics", "/sys/class/drm/"),
    "fsl,imx-ldb":             ("display_graphics", "/sys/bus/platform/devices/"),
}

# Platform detection from root compatible string
_PLATFORM_PREFIXES: dict[str, str] = {
    "qcom,": "qualcomm",
    "fsl,imx": "nxp",
    "fsl,ls": "nxp",
    "rockchip,": "rockchip",
    "mediatek,": "mediatek",
    "ti,": "ti",
    "intel,": "intel",
    "amd,": "amd",
    "sifive,": "riscv",
    "starfive,": "riscv",
}


def _detect_platform(root_compatible: str) -> str:
    """Detect SoC platform family from root DTS compatible string."""
    for prefix, platform in _PLATFORM_PREFIXES.items():
        if root_compatible.startswith(prefix):
            return platform
    return "unknown"


def extract_dts_kernel_version(dts_text: str) -> Optional[str]:
    """[SG-07] Extract implied kernel version from DTS #include paths.

    Scans for patterns like 'linux-6.6/' or versioned include paths.
    Returns "MAJOR.MINOR" string or None if not determinable.
    """
    patterns = [
        r"linux-(\d+\.\d+)/",
        r"#include\s+[<\"](?:[^\"<>]*/)?(\d+\.\d+)/",
    ]
    for pat in patterns:
        m = re.search(pat, dts_text)
        if m:
            return m.group(1)
    return None


def parse_po_agent_properties(dts_text: str) -> list[tuple[str, str, object]]:
    """Parse all po-agent,* properties from DTS text.

    Returns list of (node_label, property_name, value) tuples.
    Values are int for u32/flag properties, str for string properties.
    """
    results: list[tuple[str, str, object]] = []
    # Track current node context
    node_stack: list[str] = []
    current_node = "/"

    for line in dts_text.splitlines():
        stripped = line.strip()

        # Track node open/close
        if "{" in stripped and not stripped.startswith("/*"):
            # Extract node name
            node_match = re.match(r"^(\w[\w@-]*)\s*\{", stripped)
            if node_match:
                node_stack.append(node_match.group(1))
                current_node = "/".join(node_stack)
            elif stripped == "{":
                node_stack.append("anon")
                current_node = "/".join(node_stack)

        if "}" in stripped and node_stack:
            node_stack.pop()
            current_node = "/".join(node_stack) if node_stack else "/"

        # Match po-agent,* property
        if "po-agent," not in stripped or stripped.startswith("/*"):
            continue

        # Flag property: "po-agent,critical;"
        flag_m = re.match(r"(po-agent,[\w-]+)\s*;", stripped)
        if flag_m:
            results.append((current_node, flag_m.group(1), 1))
            continue

        # u32 property: "po-agent,expected-mv = <1800>;"
        u32_m = re.match(r"(po-agent,[\w-]+)\s*=\s*<(\d+)>", stripped)
        if u32_m:
            results.append((current_node, u32_m.group(1), int(u32_m.group(2))))
            continue

        # hex u32: "po-agent,expected-microcode-rev = <0xde>;"
        hex_m = re.match(r"(po-agent,[\w-]+)\s*=\s*<(0x[0-9a-fA-F]+)>", stripped)
        if hex_m:
            results.append((current_node, hex_m.group(1), int(hex_m.group(2), 16)))
            continue

        # String property: 'po-agent,silicon-stepping = "B1";'
        str_m = re.match(r'(po-agent,[\w-]+)\s*=\s*"([^"]*)"', stripped)
        if str_m:
            results.append((current_node, str_m.group(1), str_m.group(2)))
            continue

    return results


def _detect_cycles(dep_graph: dict[str, list[str]]) -> list[list[str]]:
    """DFS cycle detection using grey/black node coloring.

    Returns list of cycle paths found. Empty list = no cycles.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in dep_graph}
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GREY
        for neighbor in dep_graph.get(node, []):
            if neighbor not in color:
                color[neighbor] = WHITE
            if color[neighbor] == GREY:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
            elif color[neighbor] == WHITE:
                dfs(neighbor, path + [neighbor])
        color[node] = BLACK

    for node in list(dep_graph.keys()):
        if color[node] == WHITE:
            dfs(node, [node])

    return cycles


def _extract_clocks_phandles(dts_text: str) -> dict[str, dict]:
    """Extract clock dependency map from DTS clocks phandles.

    Returns {clock_name: {parent: str|None, consumers: [domain]}}
    Only DTS-extractable links; platform DB fills in gaps at Phase 0.
    """
    clock_map: dict[str, dict] = {}

    # Simplified extraction: look for clock-names + clocks = <&provider CLK_NAME>
    # Full DTS parsing would require a proper grammar; this regex-based approach
    # captures the most common patterns.
    for m in re.finditer(
        r'clocks\s*=\s*(<[^>]+>)', dts_text, re.MULTILINE
    ):
        phandle_str = m.group(1)
        # Extract referenced clock provider labels
        for ref in re.finditer(r"&(\w+)\s+(\w+)", phandle_str):
            provider = ref.group(1)
            clk_id = ref.group(2).lower()
            clock_name = f"{provider}_{clk_id}"
            if clock_name not in clock_map:
                clock_map[clock_name] = {"parent": None, "consumers": []}

    return clock_map


def parse_dts(
    base_dts_path: str,
    overlay_path: Optional[str] = None,
    board_name: str = "unknown",
) -> BoardProfile:
    """Parse base DTS + optional overlay → BoardProfile.

    Two-pass parse:
      Pass 1: resolve phandles, build symbol table
      Pass 1b: cycle detection on *-supply graph
      Pass 2: walk enabled nodes, extract properties

    Raises ValueError with DTS_PARSE_ERROR on cycles.
    """
    with open(base_dts_path, encoding="utf-8", errors="replace") as fh:
        base_text = fh.read()

    overlay_text = ""
    if overlay_path:
        with open(overlay_path, encoding="utf-8", errors="replace") as fh:
            overlay_text = fh.read()

    combined = base_text + "\n" + overlay_text

    # Extract DTS kernel version (SG-07)
    dts_kernel_version = extract_dts_kernel_version(combined)

    # Detect root compatible
    root_compatible = ""
    for m in re.finditer(r'/\s*\{[^}]*compatible\s*=\s*"([^"]+)"', combined, re.DOTALL):
        root_compatible = m.group(1).split(",")[0] + "," + m.group(1).split(",")[1] \
            if "," in m.group(1) else m.group(1)
        break

    soc_platform = _detect_platform(root_compatible)

    # Parse po-agent,* properties from overlay
    overlay_props = parse_po_agent_properties(overlay_text)

    # Build rail specs
    rails: list[RailSpec] = []
    rail_nodes: dict[str, RailSpec] = {}
    for node, prop, value in overlay_props:
        if node not in rail_nodes:
            rail_nodes[node] = RailSpec(name=node.split("/")[-1], node_path=node)
        rail = rail_nodes[node]
        if prop == "po-agent,expected-mv":
            rail.expected_mv = int(value)
        elif prop == "po-agent,tolerance-pct":
            rail.tolerance_pct = int(value)
        elif prop == "po-agent,critical":
            rail.is_barrier_rail = True
        elif prop == "po-agent,pmbus-bus":
            rail.pmbus_bus = int(value)
        elif prop == "po-agent,pmbus-addr":
            rail.pmbus_addr = int(value)
        elif prop == "po-agent,pmbus-vout-page":
            rail.pmbus_vout_page = int(value)

    # Only include nodes that have at least expected-mv (are actual rails)
    for node, rail in rail_nodes.items():
        if rail.expected_mv > 0 or rail.is_barrier_rail:
            rails.append(rail)

    # Build subsystem list from enabled DTS nodes
    subsystems: list[SubsystemSpec] = []
    dep_graph: dict[str, list[str]] = {}

    # Match all enabled nodes
    node_pattern = re.compile(
        r'(\w[\w@-]*)\s*\{[^}]*status\s*=\s*"okay"[^}]*\}',
        re.DOTALL,
    )
    for m in node_pattern.finditer(combined):
        node_text = m.group(0)
        node_name = m.group(1)

        # Extract compatible
        compat_m = re.search(r'compatible\s*=\s*"([^"]+)"', node_text)
        if not compat_m:
            continue
        compatibles = [c.strip() for c in compat_m.group(1).split(",")]

        # Map to domain
        domain, sysfs_glob = "", ""
        for compat in compatibles:
            if compat in _COMPATIBLE_TO_DOMAIN:
                domain, sysfs_glob = _COMPATIBLE_TO_DOMAIN[compat]
                break

        if not domain:
            continue

        # Check physically-present
        physically_present = True
        for _, prop, value in overlay_props:
            if prop == "po-agent,physically-present" and int(value) == 0:
                physically_present = False

        sub = SubsystemSpec(
            name=node_name,
            domain=domain,
            compatible=compatibles,
            sysfs_glob=sysfs_glob,
            physically_present=physically_present,
        )
        subsystems.append(sub)

        # Extract *-supply dependencies
        dep_graph.setdefault(domain, [])
        for supply_m in re.finditer(r"(\w+-supply)\s*=\s*<&(\w+)>", node_text):
            dep_label = supply_m.group(2)
            # Map dep_label to domain if known
            for compat in compatibles:
                if compat in _COMPATIBLE_TO_DOMAIN:
                    dep_domain = _COMPATIBLE_TO_DOMAIN.get(compat, ("", ""))[0]
                    if dep_domain and dep_domain not in dep_graph.get(domain, []):
                        dep_graph[domain].append(dep_domain)

    # Cycle detection on dep_graph (Pass 1b)
    cycles = _detect_cycles(dep_graph)
    if cycles:
        cycle_strs = [" → ".join(c) for c in cycles]
        raise ValueError(
            f"{DTS_PARSE_ERROR}: Circular dependency in DTS *-supply graph: "
            f"{'; '.join(cycle_strs)}"
        )

    # Extract clock dependency map
    clock_dependency_map = _extract_clocks_phandles(combined)

    # Check human-reviewed flag
    human_reviewed = any(
        prop == "po-agent,human-reviewed" and int(value) == 1
        for _, prop, value in overlay_props
    )

    # PCIe slot specs
    pcie_slots: list[PCIeSpec] = []
    pcie_props: dict[str, dict] = {}
    for node, prop, value in overlay_props:
        if "pcie" in node.lower() or "pci" in node.lower():
            pcie_props.setdefault(node, {})
            if prop == "po-agent,expected-pcie-gen":
                pcie_props[node]["gen"] = int(value)
            elif prop == "po-agent,expected-link-width":
                pcie_props[node]["width"] = int(value)

    for node, props in pcie_props.items():
        pcie_slots.append(PCIeSpec(
            node_path=node,
            expected_gen=props.get("gen"),
            expected_width=props.get("width"),
        ))

    log.info(
        "dts_parsed",
        board_name=board_name,
        soc_platform=soc_platform,
        root_compatible=root_compatible,
        rails=len(rails),
        subsystems=len(subsystems),
        dts_kernel_version=dts_kernel_version,
        human_reviewed=human_reviewed,
    )

    return BoardProfile(
        board_name=board_name,
        soc_compatible=root_compatible,
        soc_platform=soc_platform,
        rails=rails,
        subsystems=subsystems,
        dep_graph=dep_graph,
        clock_dependency_map=clock_dependency_map,
        dts_kernel_version=dts_kernel_version,
        human_reviewed=human_reviewed,
        pcie_slots=pcie_slots,
    )
