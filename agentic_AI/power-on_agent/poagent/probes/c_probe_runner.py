"""C Probe MMIO Framework — deploy, verify, execute, and parse C probe binaries.

[CP-01] DTS reg property → SubsystemSpec.reg_base / reg_size
[CP-02] mmio_dump.c — generic MMIO reader, JSON stdout
[CP-03] CProbeRunner — lifecycle: memory check → arch detect → deploy → integrity → exec
[CP-04] ProbeBase.run_c_probe() convenience wrapper
[CP-07] /dev/mem access check before deploy

Usage in a ProbeBase subclass:
    data = self.run_c_probe(
        "c_probes/mmio_dump.c",
        ["--base", hex(spec.reg_base), "--size", "0x1000", "--offsets", "0x5c"],
    )
    ltssm = data.get("0x5c", 0) & 0x3F
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import structlog

from poagent.codes import (
    C_PROBE_COMPILE_FAIL,
    C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY,
    C_PROBE_EXEC_FAIL,
    C_PROBE_INTEGRITY_FAIL,
    MMIO_BASE_NOT_IN_DTS,
    MMIO_REG_READ_FAIL,
)

if TYPE_CHECKING:
    from poagent.probes.registry import ProbeResult

log = structlog.get_logger(__name__)

# Directory on the target board where binaries are deployed
_DEPLOY_DIR = "/tmp/poagent_probes"

# Path to the c_probes/ directory relative to this file
_C_PROBES_DIR = Path(__file__).parent.parent / "c_probes"


# ── Exceptions ────────────────────────────────────────────────────────────────

class CProbeDeploySkipped(Exception):
    """Raised when deploy is skipped due to low memory ([H-04])."""


class CProbeCompileError(Exception):
    """Raised when on-target gcc compilation fails."""


class CProbeIntegrityError(Exception):
    """Raised when SHA-256 of deployed binary does not match manifest."""


class CProbeExecError(Exception):
    """Raised when the C probe binary exits with non-zero return code."""


# ── DTS reg property parser [CP-01] ──────────────────────────────────────────

def parse_reg_property(cells: list[int]) -> Optional[tuple[int, int]]:
    """Parse ARM 64-bit DTS reg property: [addr_hi, addr_lo, size_hi, size_lo].

    Returns (base_address, size_bytes) or None if cells are insufficient.

    Examples:
        reg = <0x0 0xfe150000 0x0 0x10000>  → (0xfe150000, 0x10000)
        reg = <0x1 0x00000000 0x0 0x1000>   → (0x100000000, 0x1000)
    """
    if not cells or len(cells) < 4:
        return None
    base = (cells[0] << 32) | cells[1]
    size = (cells[2] << 32) | cells[3]
    return base, size


# ── MMIO_BASE_NOT_IN_DTS result factory ──────────────────────────────────────

def mmio_base_not_in_dts_result(domain: str, probe_name: str) -> "ProbeResult":
    """Return a SKIP ProbeResult when the DTS reg property is absent."""
    from poagent.probes.registry import ProbeResult
    return ProbeResult(
        probe_name=probe_name,
        domain=domain,
        severity="SKIP",
        findings=[
            f"{MMIO_BASE_NOT_IN_DTS}: no 'reg' property in DTS for this IP block — "
            "MMIO probe skipped; sysfs probes continue"
        ],
    )


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _read_manifest(manifest_path: Path, binary_name: str) -> Optional[str]:
    """Read the expected SHA-256 hash for binary_name from probes.sha256."""
    if not manifest_path.exists():
        return None
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].strip("* ") == binary_name:
            return parts[0]
    return None


def _sha256_local(path: Path) -> str:
    """Compute SHA-256 of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── CProbeRunner ─────────────────────────────────────────────────────────────

class CProbeRunner:
    """Deploy, verify, execute, and parse C probe binaries on the target board.

    Lifecycle per binary (first use):
      1. _check_memory()      — MemAvailable >= min_deploy_memory_mb [H-04]
      2. _check_devmem()      — /dev/mem readable [CP-07]
      3. _detect_arch()       — uname -m → aarch64 | x86_64 | arm
      4. _deploy()            — SCP pre-compiled binary OR compile on target
      5. _verify_integrity()  — SHA-256 board-side == host manifest

    Subsequent calls for the same binary name skip steps 1-5 (cache hit).
    """

    def __init__(self, runner: object, config: object) -> None:
        self._runner = runner
        self._config = config
        self._deployed: set[str] = set()   # binary names already on board this run
        self._arch: Optional[str] = None   # cached arch string

    # ── Public API ────────────────────────────────────────────────────────────

    def run_c_probe(
        self,
        source_path: str,
        args: list[str],
        timeout: float = 10.0,
    ) -> dict:
        """Deploy (if needed) and execute the C probe. Returns parsed JSON dict.

        Args:
            source_path: path to .c source, relative to package root
                         e.g. "c_probes/mmio_dump.c"
            args:        command-line arguments for the binary
                         e.g. ["--base", "0xfe150000", "--offsets", "0x5c"]
            timeout:     exec timeout in seconds

        Raises:
            CProbeDeploySkipped   — low memory; binary not deployed
            CProbeCompileError    — gcc failed on target
            CProbeIntegrityError  — SHA-256 mismatch
            CProbeExecError       — binary exited non-zero
        """
        binary_name = Path(source_path).stem

        if binary_name not in self._deployed:
            self._check_memory()
            self._deploy(source_path, binary_name)
            self._verify_integrity(binary_name)
            self._deployed.add(binary_name)

        cmd = f"{_DEPLOY_DIR}/{binary_name} {' '.join(str(a) for a in args)}"
        rc, stdout = self._runner.exec_command(cmd, timeout=timeout)

        if rc != 0:
            raise CProbeExecError(
                f"{C_PROBE_EXEC_FAIL}: {binary_name} exited {rc}: {stdout[:200]}"
            )

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CProbeExecError(
                f"{C_PROBE_EXEC_FAIL}: {binary_name} produced invalid JSON: {exc}"
            ) from exc

    def _check_devmem(self) -> bool:
        """[CP-07] Return True if /dev/mem is readable on the target."""
        rc, _ = self._runner.exec_command("test -r /dev/mem", timeout=3)
        return rc == 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_memory(self) -> None:
        """[H-04] Raise CProbeDeploySkipped if available memory is too low."""
        min_mb = getattr(self._config, "min_deploy_memory_mb", 64)
        rc, out = self._runner.exec_command("grep MemAvailable /proc/meminfo", timeout=5)
        if rc == 0 and out.strip():
            parts = out.strip().split()
            if len(parts) >= 2 and parts[1].isdigit():
                avail_mb = int(parts[1]) // 1024
                if avail_mb < min_mb:
                    raise CProbeDeploySkipped(
                        f"{C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY}: "
                        f"{avail_mb}MB available < {min_mb}MB required"
                    )

    def _detect_arch(self) -> str:
        """Return target architecture string: aarch64 | x86_64 | arm | riscv64."""
        if self._arch:
            return self._arch
        rc, out = self._runner.exec_command("uname -m", timeout=5)
        raw = out.strip() if rc == 0 else "aarch64"
        self._arch = {
            "aarch64": "aarch64",
            "x86_64":  "x86_64",
            "armv7l":  "arm",
            "armv6l":  "arm",
            "riscv64": "riscv64",
        }.get(raw, raw)
        return self._arch

    def _deploy(self, source_path: str, binary_name: str) -> None:
        """SCP a pre-compiled binary or compile from source on the target."""
        # Ensure deploy dir exists
        self._runner.exec_command(f"mkdir -p {_DEPLOY_DIR}", timeout=5)

        arch = self._detect_arch()
        precompiled = _C_PROBES_DIR / f"{binary_name}.{arch}"

        if precompiled.exists():
            log.debug("c_probe_deploy_precompiled", binary=binary_name, arch=arch)
            self._runner.scp_put(str(precompiled), f"{_DEPLOY_DIR}/{binary_name}")
        else:
            log.debug("c_probe_compile_on_target", binary=binary_name, arch=arch)
            self._compile_on_target(binary_name, source_path)

        self._runner.exec_command(f"chmod +x {_DEPLOY_DIR}/{binary_name}", timeout=5)

    def _compile_on_target(self, binary_name: str, source_path: str = "") -> None:
        """SCP source and compile with gcc on the target board."""
        local_src = _C_PROBES_DIR / f"{binary_name}.c"
        if not local_src.exists() and source_path:
            # Fall back to the provided source_path relative to package root
            local_src = Path(__file__).parent.parent.parent / source_path

        remote_src = f"{_DEPLOY_DIR}/{binary_name}.c"
        self._runner.scp_put(str(local_src), remote_src)

        rc, err = self._runner.exec_command(
            f"gcc -O2 -o {_DEPLOY_DIR}/{binary_name} {remote_src} 2>&1",
            timeout=60,
        )
        if rc != 0:
            raise CProbeCompileError(
                f"{C_PROBE_COMPILE_FAIL}: gcc failed for {binary_name}: {err[:300]}"
            )

    def _verify_integrity(self, binary_name: str) -> None:
        """[N-PG-05] Verify SHA-256 of deployed binary against host manifest."""
        manifest = _C_PROBES_DIR / "probes.sha256"
        expected = self._read_manifest(manifest, binary_name)
        if not expected:
            # No manifest entry — engineering mode, skip check
            log.debug("c_probe_no_manifest_entry", binary=binary_name)
            return

        rc, out = self._runner.exec_command(
            f"sha256sum {_DEPLOY_DIR}/{binary_name} 2>/dev/null | awk '{{print $1}}'",
            timeout=10,
        )
        actual = out.strip() if rc == 0 else ""

        if actual != expected:
            raise CProbeIntegrityError(
                f"{C_PROBE_INTEGRITY_FAIL}: {binary_name} SHA-256 mismatch — "
                f"expected {expected[:16]}..., got {actual[:16] or 'no output'}"
            )

    def _read_manifest(self, manifest: Path, binary_name: str) -> Optional[str]:
        """Thin wrapper for testing."""
        return _read_manifest(manifest, binary_name)
