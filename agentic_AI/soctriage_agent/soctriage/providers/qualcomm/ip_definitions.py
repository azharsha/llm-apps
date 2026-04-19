from typing import Any

QUALCOMM_IP_BLOCKS: list[str] = [
    "ADRENO",   # GPU (graphics + compute) — KGSL driver
    "SMMU",     # System MMU — address translation faults
    "BIMC",     # Bus Integrated Memory Controller
    "CPUss",    # CPU subsystem (Kryo cores)
    "RPM",      # Resource Power Manager
    "USB3",     # USB3 controller (DWC3)
    "QMP",      # QMP PHY (USB/PCIe/UFS)
    "UFS",      # Universal Flash Storage
    "PCIe",     # PCIe root complex
    "LLCC",     # Last Level Cache Controller
    "WCSS",     # Wireless subsystem
    "LPASS",    # Low Power Audio subsystem
    "CAMSS",    # Camera subsystem
    "VENUS",    # Video encode/decode engine
    "PMIC",     # Power Management IC (SPMI bus)
]

IP_PATTERNS:   dict[str, list[tuple[str, float]]] = {}
CASCADE_GRAPH: dict[str, list[str]]               = {}
PLAYBOOK:      dict[str, dict[str, Any]]          = {}
REGISTER_MAPS: dict[str, dict[int, str]]          = {}
HANG_RULES:    list[Any]                          = []
