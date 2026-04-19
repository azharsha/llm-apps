from typing import Any

AMD_IP_BLOCKS: list[str] = [
    "GFX", "SDMA", "GMC", "VCN", "PSP", "RLC",
    "MEC", "KFD", "IH", "DCN", "MMHUB", "GCHUB", "JPEG", "SMU",
]

IP_PATTERNS:   dict[str, list[tuple[str, float]]] = {}
CASCADE_GRAPH: dict[str, list[str]]               = {}
PLAYBOOK:      dict[str, dict[str, Any]]          = {}
REGISTER_MAPS: dict[str, dict[int, str]]          = {}
HANG_RULES:    list[Any]                          = []
