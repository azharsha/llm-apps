"""
Patch diff parser, subsystem detector, and ABI-impact checker.
"""
import re
from typing import List, Dict


# ---------------------------------------------------------------------------
# Subsystem detection
# ---------------------------------------------------------------------------

# Ordered list of (subsystem_name, [path_regex_patterns]).
# More specific patterns first — first match wins for tie-breaking.
SUBSYSTEM_PATTERNS: List[tuple] = [
    ("USB",              [r"drivers/usb/",          r"include/linux/usb"]),
    ("DRM/GPU",          [r"drivers/gpu/drm/",       r"include/drm/"]),
    ("SCSI",             [r"drivers/scsi/",          r"include/scsi/"]),
    ("NVMe",             [r"drivers/nvme/",          r"include/linux/nvme"]),
    ("NVDIMM/PMEM",      [r"drivers/nvdimm/",        r"drivers/acpi/nfit"]),
    ("Wi-Fi/Wireless",   [r"net/wireless/",          r"drivers/net/wireless/"]),
    ("Bluetooth",        [r"net/bluetooth/",         r"drivers/bluetooth/"]),
    ("Network",          [r"drivers/net/",           r"^net/",         r"include/net/"]),
    ("Filesystem",       [r"^fs/",                   r"include/linux/fs"]),
    ("Ext4",             [r"fs/ext4/"]),
    ("XFS",              [r"fs/xfs/"]),
    ("Btrfs",            [r"fs/btrfs/"]),
    ("NFS",              [r"fs/nfs",                 r"fs/nfsd/"]),
    ("x86",              [r"arch/x86/"]),
    ("ARM64",            [r"arch/arm64/"]),
    ("ARM",              [r"arch/arm/"]),
    ("RISC-V",           [r"arch/riscv/"]),
    ("MIPS",             [r"arch/mips/"]),
    ("PowerPC",          [r"arch/powerpc/"]),
    ("Memory Management",[r"^mm/",                   r"include/linux/mm"]),
    ("Scheduler",        [r"kernel/sched/"]),
    ("Tracing/BPF",      [r"kernel/trace/",         r"kernel/bpf/",   r"tools/bpf/"]),
    ("KVM",              [r"arch/.*/kvm/",           r"virt/kvm/"]),
    ("Block Layer",      [r"^block/",                r"include/linux/blk"]),
    ("Device Mapper",    [r"drivers/md/dm-",         r"include/linux/device-mapper"]),
    ("RAID/MD",          [r"drivers/md/"]),
    ("Sound/ALSA",       [r"^sound/",                r"include/sound/"]),
    ("Security/LSM",     [r"^security/",             r"include/linux/security"]),
    ("Crypto",           [r"^crypto/",               r"include/crypto/"]),
    ("PCI",              [r"drivers/pci/",           r"include/linux/pci"]),
    ("ACPI",             [r"drivers/acpi/",          r"include/linux/acpi"]),
    ("I2C",              [r"drivers/i2c/"]),
    ("SPI",              [r"drivers/spi/"]),
    ("GPIO",             [r"drivers/gpio/",          r"include/linux/gpio"]),
    ("Input",            [r"drivers/input/",         r"include/linux/input"]),
    ("Thermal",          [r"drivers/thermal/"]),
    ("Clock",            [r"drivers/clk/"]),
    ("Regulator",        [r"drivers/regulator/"]),
    ("Watchdog",         [r"drivers/watchdog/"]),
    ("RTC",              [r"drivers/rtc/"]),
    ("MTD/Flash",        [r"drivers/mtd/"]),
    ("HID",              [r"drivers/hid/"]),
    ("IIO",              [r"drivers/iio/"]),
    ("Pinctrl",          [r"drivers/pinctrl/"]),
    ("DMA Engine",       [r"drivers/dma/"]),
    ("MMC/SD",           [r"drivers/mmc/"]),
    ("Media/V4L2",       [r"drivers/media/",        r"include/media/"]),
    ("TTY/Serial",       [r"drivers/tty/"]),
    ("ATA/SATA",         [r"drivers/ata/"]),
    ("HWMon",            [r"drivers/hwmon/"]),
    ("EDAC",             [r"drivers/edac/"]),
    ("FPGA",             [r"drivers/fpga/"]),
    ("Remote Proc",      [r"drivers/remoteproc/"]),
    ("LED",              [r"drivers/leds/"]),
    ("CAN/Net",          [r"drivers/net/can/",      r"net/can/"]),
    ("IOMMU",            [r"drivers/iommu/"]),
    ("VFIO",             [r"drivers/vfio/"]),
    ("Virtio",           [r"drivers/virtio/"]),
    ("Power Management", [r"drivers/base/power/",   r"include/linux/pm"]),
    ("IRQ",              [r"kernel/irq/"]),
    ("Locking",          [r"kernel/locking/"]),
    ("RCU",              [r"kernel/rcu/"]),
    ("cgroup",           [r"kernel/cgroup/",        r"include/linux/cgroup"]),
    ("Device Tree",      [r"arch/.*/dts/",           r"Documentation/devicetree/"]),
    ("Kernel Core",      [r"^kernel/",              r"include/linux/"]),
]

# Subsystem hints derived from the bracket prefix, e.g. "[PATCH] usb: fix"
SUBJECT_SUBSYSTEM_MAP: Dict[str, str] = {
    "usb": "USB", "drm": "DRM/GPU", "scsi": "SCSI", "nvme": "NVMe",
    "net": "Network", "netdev": "Network", "wifi": "Wi-Fi/Wireless",
    "wireless": "Wi-Fi/Wireless", "bluetooth": "Bluetooth",
    "fs": "Filesystem", "ext4": "Ext4", "xfs": "XFS", "btrfs": "Btrfs",
    "nfs": "NFS", "vfs": "Filesystem",
    "x86": "x86", "arm64": "ARM64", "arm": "ARM", "riscv": "RISC-V",
    "mips": "MIPS", "powerpc": "PowerPC",
    "mm": "Memory Management", "sched": "Scheduler",
    "bpf": "Tracing/BPF", "tracing": "Tracing/BPF", "perf": "Tracing/BPF",
    "kvm": "KVM", "block": "Block Layer", "md": "RAID/MD",
    "alsa": "Sound/ALSA", "sound": "Sound/ALSA", "asoc": "Sound/ALSA",
    "security": "Security/LSM", "crypto": "Crypto",
    "pci": "PCI", "acpi": "ACPI", "i2c": "I2C", "spi": "SPI",
    "gpio": "GPIO", "input": "Input", "thermal": "Thermal",
    "clk": "Clock", "regulator": "Regulator", "watchdog": "Watchdog",
    "rtc": "RTC", "mtd": "MTD/Flash", "hid": "HID", "iio": "IIO",
    "pinctrl": "Pinctrl", "dmaengine": "DMA Engine", "mmc": "MMC/SD",
    "media": "Media/V4L2", "v4l2": "Media/V4L2",
    "tty": "TTY/Serial", "serial": "TTY/Serial", "ata": "ATA/SATA",
    "pm": "Power Management", "cpufreq": "Power Management",
    "irq": "IRQ", "locking": "Locking", "rcu": "RCU",
    "cgroup": "cgroup", "dm": "Device Mapper",
    "hwmon": "HWMon", "hwmon/thermal": "Thermal",
    "edac": "EDAC", "fpga": "FPGA",
    "led": "LED", "leds": "LED",
    "iommu": "IOMMU", "vfio": "VFIO", "virtio": "Virtio",
    "can": "CAN/Net", "remoteproc": "Remote Proc",
}


# ---------------------------------------------------------------------------
# Memory leak detection
# ---------------------------------------------------------------------------

# Each entry: (regex_pattern, human_readable_description)
# Patterns operate on the unified diff text (including +/- prefix characters).
MEMORY_LEAK_PATTERNS: List[tuple] = [
    # Removed explicit heap deallocations — strong signal
    (r"^-[ \t]*(?:kfree|vfree|kvfree|kfree_sensitive)\s*\(",
     "Memory deallocation removed (kfree/vfree)"),

    (r"^-[ \t]*kmem_cache_free\s*\(",
     "Slab cache free removed"),

    (r"^-[ \t]*(?:kfree_skb|consume_skb|dev_kfree_skb|dev_kfree_skb_any)\s*\(",
     "sk_buff free removed"),

    # Removed reference count / resource release calls
    (r"^-[ \t]*(?:put_device|kobject_put|kref_put|dev_put|module_put|"
     r"of_node_put|fwnode_handle_put|clk_put|regulator_put|"
     r"pm_runtime_put|dma_buf_put|drm_dev_put)\s*\(",
     "Reference count or resource put removed"),

    (r"^-[ \t]*(?:free_irq|devm_free_irq|irq_dispose_mapping)\s*\(",
     "IRQ handler release removed"),

    (r"^-[ \t]*release_firmware\s*\(",
     "Firmware release removed"),

    (r"^-[ \t]*(?:dma_free_coherent|dma_free_attrs|dma_unmap_single|"
     r"dma_unmap_page|dma_unmap_sg)\s*\(",
     "DMA buffer or mapping release removed"),

    # Removed error-path cleanup goto labels
    (r"^-[ \t]*\w*(?:free|cleanup|unwind|release|err_alloc)\w*\s*:",
     "Error-path cleanup label removed"),

    # Added heap allocations — Claude should verify error paths free them
    (r"^\+[ \t]*(?:kmalloc|kzalloc|kvmalloc|kcalloc|krealloc|vmalloc|kvzalloc|"
     r"kmem_cache_alloc|kmem_cache_zalloc|alloc_pages|__get_free_pages|"
     r"get_zeroed_page|devm_kmalloc|devm_kzalloc|devm_kcalloc)\s*\(",
     "Heap allocation added — verify all error paths free this memory"),

    # Early return added after an allocation site (may skip cleanup)
    (r"^\+[ \t]*return\s+(?:PTR_ERR\s*\(|ERR_PTR\s*\(|-E[A-Z]+\b|ret\b|err\b)",
     "Error return added — verify preceding allocations are freed on this path"),

    # Commit message mentions a leak
    (r"(?i)\b(?:memory\s+leak|resource\s+leak|use.after.free|leak\s+fix|fix\s+leak)\b",
     "Commit message mentions a memory or resource leak"),
]


def check_memory_leaks(diff: str, subject: str = "", commit_msg: str = "") -> List[Dict]:
    """
    Scan diff and commit message for potential memory leak indicators.

    Returns a list of flag dicts: {type: str, occurrences: int}.
    """
    combined = "\n".join([diff, subject, commit_msg])
    flags = []
    for pattern, description in MEMORY_LEAK_PATTERNS:
        matches = re.findall(pattern, combined, re.MULTILINE)
        if matches:
            flags.append({"type": description, "occurrences": len(matches)})
    return flags


# ---------------------------------------------------------------------------
# ABI / breaking-change detection
# ---------------------------------------------------------------------------

# Each entry: (regex_pattern, human_readable_description)
ABI_BREAKING_PATTERNS: List[tuple] = [
    # Removed EXPORT_SYMBOL lines
    (r"^-[ \t]*EXPORT_SYMBOL(?:_GPL|_NS_GPL|_NS)?\s*\(\s*\w+\s*\)",
     "Removed exported symbol"),

    # UAPI header modification
    (r"include/uapi/",
     "UAPI header modified (userspace ABI)"),

    # ioctl number changed
    (r"^-[ \t]*#define\s+\w+\s+_IOC[WRC]?\(",
     "ioctl definition removed or changed"),

    # Explicit mention of ABI/breaking in commit message or diff context
    (r"(?i)\b(?:abi|api)\s+(?:break|incompatib|change|remov)",
     "ABI/API break mentioned"),

    # Support removed / dropped
    (r"(?i)\b(?:remove[sd]?|drop[ps]?|eliminat(?:e[sd]?|ing))\s+"
     r"(?:support|compat|backward.?compat)",
     "Backward compatibility removed"),

    # Userspace-visible change
    (r"(?i)userspace[-\s](?:visible|facing|break|impact)",
     "Userspace-visible change"),

    # Deprecated annotation removed
    (r"^-[ \t]*.*__deprecated",
     "Deprecated annotation removed"),

    # Symbol renamed
    (r"(?i)\b(?:rename[sd]?)\s+\w+\s+to\s+\w+",
     "Symbol renamed"),

    # sysfs / debugfs entry removed
    (r"^-.*(?:sysfs_create|debugfs_create)_",
     "sysfs/debugfs entry removed"),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def extract_files_changed(diff: str) -> List[str]:
    """Return deduplicated list of file paths touched in a unified diff."""
    files = set()
    for line in diff.splitlines():
        # Match both "--- a/path" and "+++ b/path"
        if line.startswith(("--- a/", "+++ b/")):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.add(path)
    return sorted(files)


def detect_subsystem(files_changed: List[str], subject: str = "") -> str:
    """
    Identify the primary kernel subsystem for a patch.

    Strategy (in order):
    1. Parse the subsystem tag from the subject bracket prefix, e.g. ``[PATCH] usb: fix …``
    2. Score each file against SUBSYSTEM_PATTERNS and return the best match.
    3. Fall back to "General/Other".
    """
    # 1. Subject-based hint
    # Subject may look like: "[PATCH v2 2/5] usb: ehci: fix something"
    # or "[PATCH] drivers/usb: fix something"
    subj_lower = subject.lower()

    # Try the "subsystem: description" prefix after the bracket
    colon_match = re.search(r"\]\s*([\w/]+)\s*:", subj_lower)
    if colon_match:
        raw = colon_match.group(1).split("/")[0].strip()
        if raw in SUBJECT_SUBSYSTEM_MAP:
            return SUBJECT_SUBSYSTEM_MAP[raw]

    # 2. File-path scoring
    if files_changed:
        scores: Dict[str, int] = {}
        for subsystem_name, patterns in SUBSYSTEM_PATTERNS:
            for filepath in files_changed:
                for pat in patterns:
                    if re.search(pat, filepath):
                        scores[subsystem_name] = scores.get(subsystem_name, 0) + 1
        if scores:
            return max(scores, key=scores.get)

    return "General/Other"


def check_abi_breaking(diff: str, subject: str = "", commit_msg: str = "") -> List[Dict]:
    """
    Scan diff and commit message for ABI / breaking-change indicators.

    Returns a list of flag dicts: {type: str, occurrences: int}.
    """
    combined = "\n".join([diff, subject, commit_msg])
    flags = []
    for pattern, description in ABI_BREAKING_PATTERNS:
        matches = re.findall(pattern, combined, re.MULTILINE)
        if matches:
            flags.append({"type": description, "occurrences": len(matches)})
    return flags


def parse_diff_stats(diff: str) -> Dict:
    """Return line-level add/delete/file counts for a diff."""
    if not diff:
        return {"files": 0, "additions": 0, "deletions": 0, "net_change": 0}

    additions = sum(
        1 for ln in diff.splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    )
    deletions = sum(
        1 for ln in diff.splitlines()
        if ln.startswith("-") and not ln.startswith("---")
    )
    files = len(extract_files_changed(diff))
    return {
        "files": files,
        "additions": additions,
        "deletions": deletions,
        "net_change": additions - deletions,
    }


def parse_patch_subject(subject: str) -> Dict:
    """
    Decompose a patch subject line into its components.

    Example input:  ``[PATCH v3 2/4] usb: ehci: fix suspend race``
    Returns:
        version:        3  (or None)
        patch_num:      2  (or None)
        total_patches:  4  (or None)
        description:    "usb: ehci: fix suspend race"
    """
    result: Dict = {
        "raw": subject,
        "version": None,
        "patch_num": None,
        "total_patches": None,
        "description": subject,
    }

    # Strip the [PATCH …] prefix to get the real description
    bracket_match = re.match(r"\[[^\]]+\]\s*(.*)", subject)
    if bracket_match:
        result["description"] = bracket_match.group(1).strip()

    version_match = re.search(r"\bv(\d+)\b", subject, re.IGNORECASE)
    if version_match:
        result["version"] = int(version_match.group(1))

    num_match = re.search(r"\b(\d+)/(\d+)\b", subject)
    if num_match:
        result["patch_num"] = int(num_match.group(1))
        result["total_patches"] = int(num_match.group(2))

    return result
