from __future__ import annotations
from typing import Any
from soctriage.core.soc_provider import HangRule

NVIDIA_IP_BLOCKS: list[str] = [
    "GPC", "SM", "L2", "FBPA", "NVLink",
    "PCIe", "PMU", "SEC2", "GSP", "DISPLAY",
]

# IP_PATTERNS kept for scaffold compatibility
IP_PATTERNS: dict[str, list[tuple[str, float]]] = {}

# (token_type, raw_substring, ip, confidence, subsystem)
CLASSIFY_RULES: list[tuple[str, str, str, float, str]] = [
    ("gpu_event",      "gr",          "GPC",     0.88, "gpu"),
    ("gpu_event",      "GPC",         "GPC",     0.88, "gpu"),
    ("gpu_event",      "SM",          "SM",      0.85, "gpu"),
    ("gpu_event",      "ce",          "GPC",     0.85, "gpu"),
    ("gpu_event",      "",            "GPC",     0.70, "gpu"),
    ("reset_event",    "GPU reset",   "GPC",     0.85, "gpu"),
    ("reset_event",    "nvidia",      "GPC",     0.78, "gpu"),
    ("firmware_event", "GSP",         "GSP",     0.95, "firmware"),
    ("firmware_event", "gsp",         "GSP",     0.95, "firmware"),
    ("firmware_event", "",            "GSP",     0.75, "firmware"),
    ("timeout_event",  "channel",     "GPC",     0.80, "gpu"),
    ("timeout_event",  "timeout",     "GPC",     0.75, "gpu"),
    ("pcie_error",     "nvidia",      "PCIe",    0.85, "interconnect"),
    ("pcie_error",     "NVRM",        "PCIe",    0.85, "interconnect"),
    ("pcie_error",     "",            "PCIe",    0.78, "interconnect"),
    ("memory_event",   "FBPA",        "FBPA",    0.90, "memory"),
    ("memory_event",   "ECC",         "FBPA",    0.90, "memory"),
    ("memory_event",   "FB",          "FBPA",    0.88, "memory"),
    ("memory_event",   "L2",          "L2",      0.85, "memory"),
    ("display_event",  "DISP",        "DISPLAY", 0.85, "display"),
    ("display_event",  "CRTC",        "DISPLAY", 0.82, "display"),
    ("encoder_event",  "NVENC",       "GPC",     0.88, "display"),
    ("encoder_event",  "NVDEC",       "GPC",     0.85, "display"),
    ("power_event",    "PMU",         "PMU",     0.85, "power"),
    ("power_event",    "TDP",         "PMU",     0.82, "power"),
    ("power_event",    "",            "PMU",     0.70, "power"),
]

CASCADE_GRAPH: dict[str, list[str]] = {
    "GSP":    ["GPC", "SM"],
    "GPC":    ["SM", "L2"],
    "FBPA":   ["L2", "GPC"],
    "PCIe":   ["GPC"],
    "NVLink": ["GPC", "FBPA"],
    "PMU":    ["GPC"],
    "L2":     ["GPC"],
}

PLAYBOOK: dict[str, dict[str, Any]] = {
    "GSP": {
        "steps": [
            "Check GSP firmware: dmesg | grep -i gsp",
            "Disable MIG mode during init: nvidia-smi -i 0 -mig 0",
            "Update driver to latest: apt install nvidia-driver-550",
            "Try: rmmod nvidia && modprobe nvidia NVreg_EnableGpuFirmware=0",
        ],
        "references": [],
        "notes": "GSP firmware timeout — common on H100 during MIG initialization.",
    },
    "GPC": {
        "steps": [
            "Check XID error: dmesg | grep -i 'xid'",
            "Reset GPU: nvidia-smi --gpu-reset",
            "Check for thermal throttling: nvidia-smi -q -d TEMPERATURE",
            "Update to latest driver",
        ],
        "references": [],
        "notes": "GPC hang — check XID code for specific cause.",
    },
    "PCIe": {
        "steps": [
            "Check AER: dmesg | grep -i aer",
            "Enable IOMMU passthrough: iommu=pt",
            "Try: nvidia-smi --format=csv --query-gpu=pcie.link.width.current",
            "Reseat GPU in PCIe slot",
        ],
        "references": [],
        "notes": "PCIe BAR access failure — often IOMMU or link width issue.",
    },
    "FBPA": {
        "steps": [
            "Check ECC errors: nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total",
            "Enable ECC: nvidia-smi -e 1",
            "Run NVIDIA DCGM diagnostic",
        ],
        "references": [],
        "notes": "Frame buffer / ECC error — potential VRAM fault.",
    },
    "PMU": {
        "steps": [
            "Check power: nvidia-smi -q -d POWER",
            "Reduce power limit: nvidia-smi -pl 300",
            "Verify PSU capacity and PCIe power connectors",
        ],
        "references": [],
        "notes": "PMU fault — power delivery or TDP exceeded.",
    },
}

REGISTER_MAPS: dict[str, dict[int, str]] = {
    "XID_STATUS": {
        0x00000001: "XID_FIFO_ERROR",
        0x00000002: "XID_STREAM_ERROR",
        0x00000040: "XID_CE_ECC",
        0x00000080: "XID_UE_ECC",
        0x80000000: "XID_FATAL",
    },
    "PGRAPH_STATUS": {
        0x00000001: "PGRAPH_IDLE",
        0x00000002: "PGRAPH_BUSY",
        0x80000000: "PGRAPH_HANG",
    },
    "PFIFO_STATUS": {
        0x00000001: "PFIFO_IDLE",
        0x00000002: "PFIFO_ACTIVE",
        0x00000004: "PFIFO_STALL",
    },
}

HANG_RULES: list[HangRule] = [
    HangRule(mode="HANG",  signals=[r"GPU hang", r"channel timeout", r"XID.*31"],  confidence=0.90),
    HangRule(mode="ERROR", signals=[r"GSP.*timeout", r"gsp.*firmware"],            confidence=0.92),
    HangRule(mode="ERROR", signals=[r"ECC.*uncorrectable", r"XID.*48"],            confidence=0.95),
    HangRule(mode="STALL", signals=[r"PFIFO.*stall", r"channel.*stuck"],           confidence=0.80),
]

KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "issue_id": "NV-HOPPER-001",
        "title": "GSP firmware timeout on H100 during multi-instance GPU init",
        "chip_gens": ["nvidia_hopper"],
        "symptoms": ["firmware_event", "gpu_hang"],
        "workaround": "Disable MIG mode during init: nvidia-smi -i 0 -mig 0",
        "fixed_in": "535.86.10",
        "severity": "critical",
        "url": "",
    },
    {
        "issue_id": "NV-AMPERE-001",
        "title": "PCIe BAR2 access failure on A100 SXM with IOMMU enabled",
        "chip_gens": ["nvidia_ampere"],
        "symptoms": ["pcie_error", "smmu_fault"],
        "workaround": "Add iommu=pt to kernel cmdline",
        "fixed_in": "520.61.05",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-TURING-001",
        "title": "TU102 NVLink fabric timeout during multi-GPU all-reduce",
        "chip_gens": ["nvidia_turing"],
        "symptoms": ["gpu_hang", "timeout_event"],
        "workaround": "Reduce NVLink bandwidth: nvidia-smi nvlink -r 0",
        "fixed_in": "470.82.01",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-HOPPER-002",
        "title": "H100 PCIe SXM HBM3 ECC uncorrectable error under DGEMM workload",
        "chip_gens": ["nvidia_hopper"],
        "symptoms": ["memory_event"],
        "workaround": "Enable XID 48 watchdog: nvidia-smi -e 1",
        "fixed_in": "Pending",
        "severity": "critical",
        "url": "",
    },
    {
        "issue_id": "NV-AMPERE-002",
        "title": "A10G display engine hang during GPU sharing on vGPU",
        "chip_gens": ["nvidia_ampere"],
        "symptoms": ["display_event", "gpu_hang"],
        "workaround": "Disable display on compute-only node: nvidia-smi -pm 1",
        "fixed_in": "525.105.17",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-BLACKWELL-001",
        "title": "B100 GSP init failure with secure boot and MOK not enrolled",
        "chip_gens": ["nvidia_blackwell"],
        "symptoms": ["firmware_event"],
        "workaround": "Enroll NVIDIA MOK or disable secure boot",
        "fixed_in": "Pending",
        "severity": "critical",
        "url": "",
    },
    {
        "issue_id": "NV-TURING-002",
        "title": "RTU102 NVENC encoder hang on 8K H.265 encode",
        "chip_gens": ["nvidia_turing"],
        "symptoms": ["encoder_event", "gpu_hang"],
        "workaround": "Limit encode to 4K or use H.264",
        "fixed_in": "515.65.01",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-AMPERE-003",
        "title": "A100 PMU power sensor reporting 0W after driver reload",
        "chip_gens": ["nvidia_ampere"],
        "symptoms": ["power_event"],
        "workaround": "Reload driver: rmmod nvidia && modprobe nvidia",
        "fixed_in": "530.30.02",
        "severity": "warning",
        "url": "",
    },
    {
        "issue_id": "NV-HOPPER-003",
        "title": "H800 NVLink switch fabric CRC error at high bandwidth",
        "chip_gens": ["nvidia_hopper"],
        "symptoms": ["gpu_hang", "timeout_event"],
        "workaround": "Reduce NVLink bandwidth to 80%",
        "fixed_in": "Pending",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-TURING-003",
        "title": "TU104 SEC2 authentication failure on signed userspace driver",
        "chip_gens": ["nvidia_turing"],
        "symptoms": ["firmware_event"],
        "workaround": "Use open-source kernel modules: nvidia-open",
        "fixed_in": "545.23.06",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-BLACKWELL-002",
        "title": "B200 PCIe Gen6 link training unstable above x8 lanes",
        "chip_gens": ["nvidia_blackwell"],
        "symptoms": ["pcie_error"],
        "workaround": "Force PCIe Gen5: BIOS PCIe speed override",
        "fixed_in": "Pending",
        "severity": "error",
        "url": "",
    },
    {
        "issue_id": "NV-AMPERE-004",
        "title": "A40 GPU reset failure during vGPU live migration",
        "chip_gens": ["nvidia_ampere"],
        "symptoms": ["reset_event", "gpu_hang"],
        "workaround": "Pause workloads before live migration",
        "fixed_in": "Pending",
        "severity": "critical",
        "url": "",
    },
]
