from typing import Any

INTEL_IP_BLOCKS: list[str] = [
    "GUC",      # Graphics Microcontroller — command submission
    "HUC",      # HEVC/AVC Microcontroller — media firmware auth
    "GT",       # Graphics Tile — render engine
    "RENDER",   # 3D/Compute pipeline
    "BLITTER",  # BLT engine
    "MEDIA",    # Video decode/encode
    "DISPLAY",  # Display engine (pipe A/B/C, transcoder)
    "LMEM",     # Local memory (Xe HP+)
    "GGTT",     # Global GTT — address translation
    "PCIe",     # PCIe root port / AER
    "TBT",      # Thunderbolt host controller
    "USB4",     # USB4 fabric
    "PMC",      # Power Management Controller
    "GSC",      # Graphics Security Controller (Xe2+)
    "SAMedia",  # Standalone media tile (Meteor Lake+)
]

IP_PATTERNS:   dict[str, list[tuple[str, float]]] = {}
CASCADE_GRAPH: dict[str, list[str]]               = {}
PLAYBOOK:      dict[str, dict[str, Any]]          = {}
REGISTER_MAPS: dict[str, dict[int, str]]          = {}
HANG_RULES:    list[Any]                          = []
