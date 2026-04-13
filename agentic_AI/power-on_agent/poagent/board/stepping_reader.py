"""[FINAL-S6] Platform-specific silicon stepping reader.

Keyed by soc_platform string from BoardProfile. Never returns None —
the universal fallback always captures raw sysfs/procfs output.

If source == "fallback", the orchestrator emits SILICON_STEPPING_UNRESOLVED
and upgrades po_verdict to CONDITIONAL minimum [LAST-S4].
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def read_silicon_stepping(runner: object, board_profile: object) -> dict:
    """Platform-specific silicon stepping reader.

    Returns a dict with at minimum:
      {"platform": str, "source": str, "raw": str}

    Never raises — the fallback catches all failures.
    """
    # runner is a ProbeRunner; board_profile is BoardProfile.
    # Using getattr to avoid circular imports at module level.
    platform: str = getattr(board_profile, "soc_platform", "unknown")

    try:
        if platform == "intel":
            return _read_intel(runner)
        elif platform == "qualcomm":
            return _read_qualcomm(runner)
        elif platform == "nxp":
            return _read_nxp(runner)
        elif platform == "rockchip":
            return _read_rockchip(runner)
        elif platform == "mediatek":
            return _read_mediatek(runner)
        elif platform == "ti":
            return _read_ti(runner)
    except Exception as exc:
        log.debug("stepping_reader_platform_failed",
                  platform=platform, error=str(exc))

    return _read_fallback(runner, platform)


def _read_intel(runner: object) -> dict:
    """Intel: CPUID leaf 0x1, EAX bits decode stepping/model/family."""
    cpuid_out = runner.exec(  # type: ignore[attr-defined]
        "cpuid -l 0x1 -r 2>/dev/null | awk '/eax/ {print $NF}' | head -1",
        timeout=5,
    ).stdout.strip()
    if not cpuid_out:
        raise ValueError("cpuid unavailable")

    eax = int(cpuid_out, 16)
    stepping = eax & 0xF
    model = ((eax >> 4) & 0xF) | (((eax >> 16) & 0xF) << 4)
    family = (eax >> 8) & 0xF
    stepping_str = _intel_stepping_label(family, model, stepping)

    # PCI revision IDs (supplementary)
    pci_revisions = _read_pci_revisions(runner)
    processor_ver = _read_dmidecode_processor(runner)

    return {
        "platform": "intel",
        "source": "cpuid",
        "family": family,
        "model": model,
        "stepping": stepping,
        "stepping_str": stepping_str,
        "pci_revisions": pci_revisions,
        "processor_ver": processor_ver,
        "raw": cpuid_out,
    }


def _read_qualcomm(runner: object) -> dict:
    rev = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/revision 2>/dev/null || echo ''",
        timeout=3,
    ).stdout.strip()
    soc_id = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/soc_id 2>/dev/null || echo ''",
        timeout=3,
    ).stdout.strip()
    if not rev:
        raise ValueError("soc0/revision unavailable")
    return {
        "platform": "qualcomm",
        "source": "soc0_revision",
        "revision": rev,
        "soc_id": soc_id,
        "raw": rev,
    }


def _read_nxp(runner: object) -> dict:
    soc_id = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/soc_id 2>/dev/null || echo ''",
        timeout=3,
    ).stdout.strip()
    rev = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/revision 2>/dev/null || echo ''",
        timeout=3,
    ).stdout.strip()
    if not soc_id:
        raise ValueError("soc0/soc_id unavailable")
    return {
        "platform": "nxp",
        "source": "soc0_revision",
        "soc_id": soc_id,
        "revision": rev,
        "raw": f"{soc_id} rev {rev}",
    }


def _read_rockchip(runner: object) -> dict:
    hw = runner.exec(  # type: ignore[attr-defined]
        "cat /proc/cpuinfo | grep Hardware | head -1 | awk -F: '{print $2}'",
        timeout=3,
    ).stdout.strip()
    rev = runner.exec(  # type: ignore[attr-defined]
        "cat /proc/cpuinfo | grep Revision | head -1 | awk -F: '{print $2}'",
        timeout=3,
    ).stdout.strip()
    if not hw:
        raise ValueError("Hardware not in /proc/cpuinfo")
    return {
        "platform": "rockchip",
        "source": "procfs",
        "hardware": hw,
        "revision": rev,
        "raw": f"{hw} rev {rev}",
    }


def _read_mediatek(runner: object) -> dict:
    devinfo = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/class/devinfo/ap/attrs 2>/dev/null || echo ''",
        timeout=3,
    ).stdout.strip()
    if devinfo:
        return {"platform": "mediatek", "source": "devinfo", "raw": devinfo}
    model = runner.exec(  # type: ignore[attr-defined]
        "cat /proc/device-tree/model 2>/dev/null | tr -d '\\0' || echo ''",
        timeout=3,
    ).stdout.strip()
    if model:
        return {"platform": "mediatek", "source": "device_tree_model", "raw": model}
    raise ValueError("No MediaTek stepping source found")


def _read_ti(runner: object) -> dict:
    rev = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/revision 2>/dev/null || "
        "cat /proc/cpuinfo | grep Revision | head -1 | awk -F: '{print $2}' || echo ''",
        timeout=3,
    ).stdout.strip()
    if not rev:
        raise ValueError("TI revision unavailable")
    return {"platform": "ti", "source": "soc0_revision", "revision": rev, "raw": rev}


def _read_fallback(runner: object, platform: str) -> dict:
    """[FINAL-S6] Universal fallback — never returns None.

    Captures raw output from the most likely sources even if platform-
    specific parsing fails. The returned dict has source="fallback" which
    triggers SILICON_STEPPING_UNRESOLVED in the orchestrator and upgrades
    po_verdict to CONDITIONAL minimum [LAST-S4].
    """
    raw = runner.exec(  # type: ignore[attr-defined]
        "cat /sys/devices/soc0/revision 2>/dev/null || "
        "cat /proc/cpuinfo | grep -i revision | head -1 || echo 'unavailable'",
        timeout=5,
    ).stdout.strip()
    return {
        "platform": platform,
        "source": "fallback",
        "raw": raw or "unavailable",
    }


def _intel_stepping_label(family: int, model: int, stepping: int) -> str:
    """Map Intel CPUID family/model/stepping to human stepping label."""
    # Tiger Lake: family=6, model=0x8C
    _TGL_MAP = {0: "A0", 1: "B1", 2: "B2"}
    if family == 6 and model == 0x8C:
        return _TGL_MAP.get(stepping, f"stepping_{stepping}")
    # Alder Lake: family=6, model=0x97
    if family == 6 and model == 0x97:
        _ADL_MAP = {0: "A0", 2: "B0", 4: "B0"}
        return _ADL_MAP.get(stepping, f"stepping_{stepping}")
    return f"stepping_{stepping}"


def _read_pci_revisions(runner: object) -> dict[str, str]:
    """Read PCI revision IDs for all devices (supplementary info)."""
    try:
        out = runner.exec(  # type: ignore[attr-defined]
            "lspci -vvv 2>/dev/null | grep -E '^[0-9a-f]|Rev '",
            timeout=10,
        ).stdout
        result: dict[str, str] = {}
        current_bdf = ""
        for line in out.splitlines():
            bdf_m = __import__("re").match(r"^([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9])", line)
            if bdf_m:
                current_bdf = bdf_m.group(1)
            elif "Rev " in line and current_bdf:
                rev_m = __import__("re").search(r"Rev\s+([0-9a-fx]+)", line, __import__("re").IGNORECASE)
                if rev_m:
                    result[current_bdf] = rev_m.group(1)
        return result
    except Exception:
        return {}


def _read_dmidecode_processor(runner: object) -> str:
    """Read processor version from dmidecode (x86 only)."""
    try:
        out = runner.exec(  # type: ignore[attr-defined]
            "dmidecode -t processor 2>/dev/null | grep 'Version:' | head -1 | awk -F: '{print $2}'",
            timeout=5,
        ).stdout.strip()
        return out
    except Exception:
        return ""
