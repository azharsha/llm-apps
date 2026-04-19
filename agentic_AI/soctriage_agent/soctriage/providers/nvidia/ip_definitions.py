from typing import Any

NVIDIA_IP_BLOCKS: list[str] = [
    "GPC",      # Graphics Processing Cluster
    "SM",       # Streaming Multiprocessor
    "L2",       # L2 Cache
    "FBPA",     # Frame Buffer Partition
    "NVLink",   # NVLink interconnect
    "PCIe",     # PCIe interface
    "PMU",      # Power Management Unit
    "SEC2",     # Security engine
    "GSP",      # GPU System Processor (firmware)
    "DISPLAY",  # Display engine
]

IP_PATTERNS:   dict[str, list[tuple[str, float]]] = {}
CASCADE_GRAPH: dict[str, list[str]]               = {}
PLAYBOOK:      dict[str, dict[str, Any]]          = {}
REGISTER_MAPS: dict[str, dict[int, str]]          = {}
HANG_RULES:    list[Any]                          = []
