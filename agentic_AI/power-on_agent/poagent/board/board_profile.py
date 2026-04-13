"""BoardProfile dataclass — parsed representation of a DTS + overlay pair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RailSpec:
    """Voltage rail specification from DTS overlay."""

    name: str
    node_path: str
    expected_mv: int = 0
    tolerance_pct: int = 5
    is_barrier_rail: bool = False   # po-agent,critical flag
    pmbus_bus: Optional[int] = None
    pmbus_addr: Optional[int] = None
    pmbus_vout_page: Optional[int] = None
    min_mv: Optional[int] = None    # from regulator-min-microvolt / 1000
    max_mv: Optional[int] = None


@dataclass
class SubsystemSpec:
    """A DTS-declared hardware subsystem."""

    name: str
    domain: str          # maps to DomainResult.domain
    compatible: list[str] = field(default_factory=list)
    node_path: str = ""
    enabled: bool = True
    physically_present: bool = True  # po-agent,physically-present
    sysfs_glob: str = ""             # expected sysfs path pattern
    dependencies: list[str] = field(default_factory=list)   # domain names
    reg_base: Optional[int] = None   # [CP-01] physical base address from DTS reg property
    reg_size: Optional[int] = None   # [CP-01] mapped region size in bytes


@dataclass
class PCIeSpec:
    """PCIe slot expectations from DTS overlay."""

    node_path: str
    expected_gen: Optional[int] = None    # po-agent,expected-pcie-gen
    expected_width: Optional[int] = None  # po-agent,expected-link-width


@dataclass
class NVMeSpec:
    """NVMe device expectations."""

    node_path: str
    expected_unsafe_shutdowns: int = 255   # ci_mode default (unchecked)


@dataclass
class UFSSpec:
    """UFS device expectations."""

    node_path: str
    expected_eol_info: int = 0x01   # 0x01 = Normal


@dataclass
class BoardProfile:
    """Parsed representation of base DTS + po-agent overlay.

    Built by dts_parser.py from the two DTS files.
    This is the single source of truth for hardware topology.
    """

    board_name: str
    soc_compatible: str = ""      # root node compatible string (e.g. "qcom,sc8280x")
    soc_platform: str = "unknown" # intel | qualcomm | nxp | rockchip | mediatek | ti | unknown

    # Rail specs from overlay
    rails: list[RailSpec] = field(default_factory=list)

    # Subsystem specs from DTS (status="okay" nodes)
    subsystems: list[SubsystemSpec] = field(default_factory=list)

    # PCIe slot expectations
    pcie_slots: list[PCIeSpec] = field(default_factory=list)

    # Storage expectations
    nvme_devices: list[NVMeSpec] = field(default_factory=list)
    ufs_devices: list[UFSSpec] = field(default_factory=list)

    # Clock phandle graph: {clock_name: {parent: str|None, consumers: list[str]}}
    clock_dependency_map: dict[str, dict] = field(default_factory=dict)

    # Dependency graph built from *-supply + phys phandles
    # {domain_name: [dep_domain_name, ...]}
    dep_graph: dict[str, list[str]] = field(default_factory=dict)

    # DTS kernel version extracted from #include paths (SG-07)
    dts_kernel_version: Optional[str] = None   # e.g. "6.1" or None

    # Human-reviewed flag from overlay
    human_reviewed: bool = False

    # Gate 4 sentinel path (from overlay or config)
    gate4_sentinel_path: str = "/tmp/poagent_ready"

    def critical_rails(self) -> list[RailSpec]:
        """Return only po-agent,critical rails (barrier rails)."""
        return [r for r in self.rails if r.is_barrier_rail]

    def subsystem_by_domain(self, domain: str) -> Optional[SubsystemSpec]:
        """Find a subsystem spec by domain name."""
        for s in self.subsystems:
            if s.domain == domain:
                return s
        return None

    def subsystem_by_compatible(self, compatible: str) -> Optional[SubsystemSpec]:
        """Find the first subsystem whose compatible list contains the given string."""
        for s in self.subsystems:
            if compatible in s.compatible:
                return s
        return None

    def topo_sort(self, target_domains: list[str] | None = None) -> list[str]:
        """Return topologically sorted domain list (dependency-safe order).

        If target_domains is provided, returns only the domains in the
        transitive closure of dependencies for those targets.
        """
        all_domains = [s.domain for s in self.subsystems if s.enabled]
        if target_domains:
            # Build transitive closure
            visited: set[str] = set()
            queue = list(target_domains)
            while queue:
                d = queue.pop()
                if d in visited:
                    continue
                visited.add(d)
                for dep in self.dep_graph.get(d, []):
                    queue.append(dep)
            all_domains = [d for d in all_domains if d in visited]

        # Kahn's algorithm for topological sort
        in_degree: dict[str, int] = {d: 0 for d in all_domains}
        for d in all_domains:
            for dep in self.dep_graph.get(d, []):
                if dep in in_degree:
                    in_degree[d] += 1

        result: list[str] = []
        queue_s = [d for d, deg in in_degree.items() if deg == 0]
        while queue_s:
            node = queue_s.pop(0)
            result.append(node)
            for d in all_domains:
                if node in self.dep_graph.get(d, []):
                    in_degree[d] -= 1
                    if in_degree[d] == 0:
                        queue_s.append(d)
        return result
