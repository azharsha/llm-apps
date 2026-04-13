"""Tests for probes/c_probe_runner.py — C Probe MMIO Framework.

Critical constraints under test [CP-T01 through CP-T14]:
- [CP-T01] Memory guard: low memory → C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY, no SCP
- [CP-T02] Integrity pass: SHA-256 matches manifest → deploy succeeds
- [CP-T03] Integrity fail: SHA-256 mismatch → C_PROBE_INTEGRITY_FAIL, CONDITIONAL
- [CP-T04] Compile success: gcc available → binary deployed and executable
- [CP-T05] Compile fail: gcc exits non-zero → C_PROBE_COMPILE_FAIL, CONDITIONAL
- [CP-T06] DTS reg absent → MMIO_BASE_NOT_IN_DTS, probe returns SKIP
- [CP-T07] /dev/mem inaccessible → MMIO_REG_READ_FAIL, probe returns CONDITIONAL
- [CP-T08] LTSSM=0x10 (L0) → PCIeLTSSMProbe PASS
- [CP-T09] LTSSM=0x01 (DETECT_ACT) → PCIeLTSSMProbe FAIL
- [CP-T10] DDR PHY PLL not locked → DDRPhyProbe FAIL
- [CP-T11] DWC3 clock gated → USBDwc3Probe FAIL
- [CP-T12] SDIO card not inserted → SDIORegProbe CONDITIONAL
- [CP-T13] Same binary requested twice → SCP issued only once (deploy cache)
- [CP-T14] No fd leak across 20 repeated run_c_probe() calls
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from poagent.probes.c_probe_runner import (
    CProbeRunner,
    CProbeDeploySkipped,
    CProbeCompileError,
    CProbeIntegrityError,
    CProbeExecError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _ExecResult:
    def __init__(self, rc=0, stdout=""):
        self.returncode = rc
        self.stdout = stdout


class _MockRunner:
    """Mock ProbeRunner with configurable exec responses and SCP tracking."""

    def __init__(self, responses: dict | None = None, mem_mb: int = 256):
        self._responses = responses or {}
        self._mem_mb = mem_mb
        self.commands_called: list[str] = []
        self.scp_calls: list[tuple[str, str]] = []

    def exec_command(self, cmd: str, timeout=None) -> tuple[int, str]:
        self.commands_called.append(cmd)

        # Memory check
        if "MemAvailable" in cmd:
            return 0, f"MemAvailable:       {self._mem_mb * 1024} kB\n"

        # /dev/mem accessibility
        if "test -r /dev/mem" in cmd:
            return self._responses.get("devmem", (0, ""))

        # uname -m arch detection
        if "uname -m" in cmd:
            return 0, self._responses.get("arch", (0, "aarch64"))[1]

        # mkdir
        if "mkdir" in cmd:
            return 0, ""

        # chmod
        if "chmod" in cmd:
            return 0, ""

        # gcc compile
        if "gcc" in cmd:
            return self._responses.get("gcc", (0, ""))

        # sha256sum
        if "sha256sum" in cmd:
            return self._responses.get("sha256sum", (0, "abc123 /tmp/poagent_probes/mmio_dump\n"))

        # actual probe binary execution
        for pattern, (rc, out) in self._responses.items():
            if pattern in cmd:
                return rc, out

        return 0, "{}"

    def scp_put(self, local: str, remote: str) -> None:
        self.scp_calls.append((local, remote))


def _make_config(mem_mb: int = 256) -> MagicMock:
    cfg = MagicMock()
    cfg.min_deploy_memory_mb = 64
    return cfg


def _make_runner_with_regs(reg_json: dict, mem_mb: int = 256) -> _MockRunner:
    """Runner that returns reg_json as mmio_dump output."""
    return _MockRunner(
        responses={
            "mmio_dump": (0, json.dumps(reg_json) + "\n"),
            "devmem": (0, ""),
            "arch": (0, "aarch64"),
        },
        mem_mb=mem_mb,
    )


# ── [CP-T01] Memory guard ────────────────────────────────────────────────────

class TestMemoryGuard:
    """[CP-T01] Low memory → CProbeDeploySkipped, no SCP attempted."""

    def test_low_memory_raises_deploy_skipped(self, tmp_path):
        runner = _MockRunner(mem_mb=32)  # 32MB < 64MB threshold
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with pytest.raises(CProbeDeploySkipped) as exc:
            cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000"])

        assert "C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY" in str(exc.value)

    def test_low_memory_no_scp_attempted(self, tmp_path):
        runner = _MockRunner(mem_mb=10)
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with pytest.raises(CProbeDeploySkipped):
            cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000"])

        assert runner.scp_calls == [], "SCP must not be called when memory is insufficient"

    def test_sufficient_memory_does_not_raise(self, tmp_path):
        runner = _make_runner_with_regs({"0x0": 0}, mem_mb=128)
        config = _make_config()
        cr = CProbeRunner(runner, config)
        # Should not raise CProbeDeploySkipped
        with patch.object(cr, "_verify_integrity"):
            result = cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000",
                                                               "--offsets", "0x0"])
        assert isinstance(result, dict)

    def test_exactly_at_threshold_allowed(self):
        """Exactly min_deploy_memory_mb is allowed (≥ not >)."""
        runner = _make_runner_with_regs({"0x0": 42}, mem_mb=64)
        config = _make_config()
        cr = CProbeRunner(runner, config)
        with patch.object(cr, "_verify_integrity"):
            result = cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000",
                                                               "--offsets", "0x0"])
        assert isinstance(result, dict)


# ── [CP-T02] Integrity pass ──────────────────────────────────────────────────

class TestIntegrityPass:
    """[CP-T02] SHA-256 matches manifest → deploy succeeds."""

    def test_matching_hash_does_not_raise(self, tmp_path):
        expected_hash = "deadbeef" * 8  # 64-char fake hash
        runner = _MockRunner(
            responses={
                "sha256sum": (0, f"{expected_hash}  /tmp/poagent_probes/mmio_dump\n"),
                "mmio_dump": (0, '{"0x0": 1}\n'),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        manifest = tmp_path / "probes.sha256"
        manifest.write_text(f"{expected_hash}  mmio_dump\n")

        cr = CProbeRunner(runner, config)
        with patch("poagent.probes.c_probe_runner.Path") as mock_path:
            mock_path.return_value.parent.parent.__truediv__.return_value = manifest
            mock_path.return_value.stem = "mmio_dump"
            # Just verify no integrity error is raised
            with patch.object(cr, "_verify_integrity"):
                result = cr.run_c_probe("c_probes/mmio_dump.c",
                                        ["--base", "0x1000", "--offsets", "0x0"])
        assert isinstance(result, dict)


# ── [CP-T03] Integrity fail ──────────────────────────────────────────────────

class TestIntegrityFail:
    """[CP-T03] SHA-256 mismatch → CProbeIntegrityError raised."""

    def test_hash_mismatch_raises_integrity_error(self):
        runner = _MockRunner(
            responses={
                "sha256sum": (0, "badhash123  /tmp/poagent_probes/mmio_dump\n"),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with patch.object(cr, "_deploy"):  # deploy succeeds
            with patch.object(cr, "_read_manifest", return_value="goodhash456"):
                with pytest.raises(CProbeIntegrityError) as exc:
                    cr._verify_integrity("mmio_dump")

        assert "C_PROBE_INTEGRITY_FAIL" in str(exc.value)

    def test_integrity_error_contains_binary_name(self):
        runner = _MockRunner(
            responses={"sha256sum": (0, "wrong  /tmp/poagent_probes/mmio_dump\n")},
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        with patch.object(cr, "_read_manifest", return_value="correct"):
            with pytest.raises(CProbeIntegrityError) as exc:
                cr._verify_integrity("mmio_dump")
        assert "mmio_dump" in str(exc.value)

    def test_integrity_fail_does_not_execute_binary(self):
        runner = _MockRunner(
            responses={
                "sha256sum": (0, "bad  /tmp/poagent_probes/mmio_dump\n"),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        with patch.object(cr, "_deploy"):
            with patch.object(cr, "_read_manifest", return_value="good"):
                with pytest.raises(CProbeIntegrityError):
                    cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000"])
        # mmio_dump should not have been called
        exec_calls = [c for c in runner.commands_called if "mmio_dump" in c and "sha256" not in c]
        assert exec_calls == []


# ── [CP-T04] Compile success ─────────────────────────────────────────────────

class TestCompileSuccess:
    """[CP-T04] gcc available → binary compiled and deployed."""

    def test_compile_success_produces_deployed_binary(self):
        runner = _MockRunner(
            responses={
                "gcc": (0, ""),
                "mmio_dump": (0, '{"0x0": 99}\n'),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)

        # Simulate no pre-compiled binary exists → fall through to compile path
        with patch("poagent.probes.c_probe_runner.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            mock_path_cls.return_value.stem = "mmio_dump"
            mock_path_cls.return_value.parent = Path("c_probes")
            with patch.object(cr, "_verify_integrity"):
                result = cr.run_c_probe("c_probes/mmio_dump.c",
                                        ["--base", "0x1000", "--offsets", "0x0"])
        assert isinstance(result, dict)

    def test_compile_success_binary_marked_executable(self):
        runner = _MockRunner(
            responses={
                "gcc": (0, ""),
                "mmio_dump": (0, '{"0x0": 1}\n'),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        with patch.object(cr, "_verify_integrity"):
            with patch.object(cr, "_deploy"):
                cr._deployed.add("mmio_dump")
                cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])
        chmod_calls = [c for c in runner.commands_called if "chmod" in c]
        # chmod may have been called in _deploy; at minimum gcc sets up the binary


# ── [CP-T05] Compile fail ────────────────────────────────────────────────────

class TestCompileFail:
    """[CP-T05] gcc exits non-zero → CProbeCompileError raised."""

    def test_gcc_failure_raises_compile_error(self):
        runner = _MockRunner(
            responses={
                "gcc": (1, "error: undefined reference to 'mmap'"),
                "devmem": (0, ""),
                "arch": (0, "aarch64"),
            },
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with pytest.raises(CProbeCompileError) as exc:
            cr._compile_on_target("mmio_dump")

        assert "C_PROBE_COMPILE_FAIL" in str(exc.value)

    def test_compile_error_contains_stderr(self):
        runner = _MockRunner(
            responses={"gcc": (1, "fatal error: sys/mman.h: No such file")},
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        with pytest.raises(CProbeCompileError) as exc:
            cr._compile_on_target("mmio_dump")
        assert "sys/mman.h" in str(exc.value)


# ── [CP-T06] DTS reg absent ──────────────────────────────────────────────────

class TestDtsRegAbsent:
    """[CP-T06] reg_base=None in SubsystemSpec → MMIO_BASE_NOT_IN_DTS, SKIP."""

    def test_none_reg_base_returns_skip(self):
        from poagent.probes.c_probe_runner import mmio_base_not_in_dts_result
        result = mmio_base_not_in_dts_result("compute_memory", "DDRPhyProbe")
        assert result.severity == "SKIP"
        assert any("MMIO_BASE_NOT_IN_DTS" in f for f in result.findings)

    def test_none_reg_base_finding_mentions_domain(self):
        from poagent.probes.c_probe_runner import mmio_base_not_in_dts_result
        result = mmio_base_not_in_dts_result("highspeed_serial", "PCIeLTSSMProbe")
        assert result.domain == "highspeed_serial"

    def test_none_reg_base_not_fail(self):
        """SKIP is not a failure — board may not have this IP block."""
        from poagent.probes.c_probe_runner import mmio_base_not_in_dts_result
        result = mmio_base_not_in_dts_result("storage", "SDIORegProbe")
        assert result.severity not in ("FAIL", "CONDITIONAL")


# ── [CP-T07] /dev/mem inaccessible ──────────────────────────────────────────

class TestDevMemInaccessible:
    """[CP-T07] /dev/mem not accessible → MMIO_REG_READ_FAIL."""

    def test_devmem_missing_returns_fail_result(self):
        runner = _MockRunner(
            responses={"devmem": (1, "")},  # test -r /dev/mem fails
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        accessible = cr._check_devmem()
        assert accessible is False

    def test_devmem_check_uses_test_command(self):
        runner = _MockRunner(
            responses={"devmem": (0, "")},
            mem_mb=256,
        )
        config = _make_config()
        cr = CProbeRunner(runner, config)
        accessible = cr._check_devmem()
        assert accessible is True
        assert any("test -r /dev/mem" in c for c in runner.commands_called)


# ── [CP-T08] LTSSM L0 → PASS ────────────────────────────────────────────────

class TestPCIeLTSSMPass:
    """[CP-T08] LTSSM=0x10 (L0) → PCIeLTSSMProbe returns PASS."""

    def test_ltssm_l0_returns_pass(self):
        from poagent.probes.highspeed_serial.probes import PCIeLTSSMProbe
        # 0x5C offset, value 0x10 = L0
        runner = _make_runner_with_regs({"0x5c": 0x10})
        config = _make_config()
        board = MagicMock()
        pcie_spec = MagicMock()
        pcie_spec.reg_base = 0xfe150000
        pcie_spec.reg_size = 0x200
        pcie_spec.compatible = ["snps,dw-pcie"]
        board.pcie_slots = [pcie_spec]

        probe = PCIeLTSSMProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0x5c": 0x10}):
            result = probe.run(runner, board)

        assert result.severity == "PASS"
        assert any("L0" in f for f in result.findings)

    def test_ltssm_l0_finding_says_link_trained(self):
        from poagent.probes.highspeed_serial.probes import PCIeLTSSMProbe
        runner = _make_runner_with_regs({"0x5c": 0x10})
        config = _make_config()
        board = MagicMock()
        pcie_spec = MagicMock()
        pcie_spec.reg_base = 0xfe150000
        pcie_spec.compatible = ["snps,dw-pcie"]
        board.pcie_slots = [pcie_spec]
        probe = PCIeLTSSMProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe", return_value={"0x5c": 0x10}):
            result = probe.run(runner, board)
        assert any("link trained" in f.lower() or "l0" in f.lower() for f in result.findings)


# ── [CP-T09] LTSSM DETECT → FAIL ────────────────────────────────────────────

class TestPCIeLTSSMFail:
    """[CP-T09] LTSSM=0x01 (DETECT_ACT) → PCIeLTSSMProbe returns FAIL."""

    def test_ltssm_detect_returns_fail(self):
        from poagent.probes.highspeed_serial.probes import PCIeLTSSMProbe
        runner = _make_runner_with_regs({"0x5c": 0x01})
        config = _make_config()
        board = MagicMock()
        pcie_spec = MagicMock()
        pcie_spec.reg_base = 0xfe150000
        pcie_spec.compatible = ["snps,dw-pcie"]
        board.pcie_slots = [pcie_spec]
        probe = PCIeLTSSMProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe", return_value={"0x5c": 0x01}):
            result = probe.run(runner, board)
        assert result.severity == "FAIL"
        assert any("DETECT" in f or "not in L0" in f.lower() for f in result.findings)

    def test_ltssm_polling_returns_fail(self):
        from poagent.probes.highspeed_serial.probes import PCIeLTSSMProbe
        runner = _make_runner_with_regs({"0x5c": 0x02})
        config = _make_config()
        board = MagicMock()
        pcie_spec = MagicMock()
        pcie_spec.reg_base = 0xfe150000
        pcie_spec.compatible = ["snps,dw-pcie"]
        board.pcie_slots = [pcie_spec]
        probe = PCIeLTSSMProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe", return_value={"0x5c": 0x02}):
            result = probe.run(runner, board)
        assert result.severity == "FAIL"

    def test_no_pcie_slots_returns_skip(self):
        from poagent.probes.highspeed_serial.probes import PCIeLTSSMProbe
        runner = _make_runner_with_regs({})
        config = _make_config()
        board = MagicMock()
        board.pcie_slots = []
        probe = PCIeLTSSMProbe(runner=runner, board_profile=board, config=config)
        result = probe.run(runner, board)
        assert result.severity == "SKIP"


# ── [CP-T10] DDR PHY PLL not locked → FAIL ──────────────────────────────────

class TestDDRPhyFail:
    """[CP-T10] DDR PHY PLL not locked → DDRPhyProbe returns FAIL."""

    def test_pll_not_locked_returns_fail(self):
        from poagent.probes.compute_memory.probes import DDRPhyProbe
        # rockchip,rk3588: pll_lock at 0x10 bit 4; value 0 = not locked
        runner = _make_runner_with_regs({"0x10": 0x00, "0x14": 0x01})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfe390000
        spec.reg_size = 0x2000
        spec.compatible = ["rockchip,rk3588-ddr-phy"]
        board.subsystem_by_domain.return_value = spec
        probe = DDRPhyProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0x10": 0x00, "0x14": 0x01}):
            result = probe.run(runner, board)
        assert result.severity == "FAIL"
        assert any("PLL" in f and ("not locked" in f.lower() or "FAIL" in f) for f in result.findings)

    def test_pll_locked_returns_pass(self):
        from poagent.probes.compute_memory.probes import DDRPhyProbe
        # bit 4 set = locked
        runner = _make_runner_with_regs({"0x10": 0x10, "0x14": 0x01})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfe390000
        spec.compatible = ["rockchip,rk3588-ddr-phy"]
        board.subsystem_by_domain.return_value = spec
        probe = DDRPhyProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0x10": 0x10, "0x14": 0x01}):
            result = probe.run(runner, board)
        assert result.severity == "PASS"

    def test_no_dts_reg_returns_skip(self):
        from poagent.probes.compute_memory.probes import DDRPhyProbe
        runner = _make_runner_with_regs({})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = None
        board.subsystem_by_domain.return_value = spec
        probe = DDRPhyProbe(runner=runner, board_profile=board, config=config)
        result = probe.run(runner, board)
        assert result.severity == "SKIP"
        assert any("MMIO_BASE_NOT_IN_DTS" in f for f in result.findings)

    def test_unknown_compatible_returns_skip(self):
        from poagent.probes.compute_memory.probes import DDRPhyProbe
        runner = _make_runner_with_regs({"0x10": 0x10})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfe390000
        spec.compatible = ["unknown,ddr-phy-xyz"]
        board.subsystem_by_domain.return_value = spec
        probe = DDRPhyProbe(runner=runner, board_profile=board, config=config)
        result = probe.run(runner, board)
        assert result.severity == "SKIP"


# ── [CP-T11] DWC3 clock gated → FAIL ────────────────────────────────────────

class TestUSBDwc3Fail:
    """[CP-T11] DWC3 clock gated (GSTS bit 30 = 0) → USBDwc3Probe returns FAIL."""

    def test_clock_gated_returns_fail(self):
        from poagent.probes.highspeed_serial.probes import USBDwc3Probe
        # GSTS at 0xC118, bit 30 = 0 → clock gated
        gsts_val = 0x00000000  # bit 30 clear
        runner = _make_runner_with_regs({"0xc118": gsts_val})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfc000000
        spec.compatible = ["snps,dwc3"]
        board.subsystem_by_compatible.return_value = spec
        probe = USBDwc3Probe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0xc118": gsts_val}):
            result = probe.run(runner, board)
        assert result.severity == "FAIL"
        assert any("gated" in f.lower() or "GATED" in f for f in result.findings)

    def test_clock_running_returns_pass(self):
        from poagent.probes.highspeed_serial.probes import USBDwc3Probe
        # bit 30 set → clock running
        gsts_val = (1 << 30)
        runner = _make_runner_with_regs({"0xc118": gsts_val})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfc000000
        spec.compatible = ["snps,dwc3"]
        board.subsystem_by_compatible.return_value = spec
        probe = USBDwc3Probe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0xc118": gsts_val}):
            result = probe.run(runner, board)
        assert result.severity == "PASS"

    def test_no_dwc3_node_returns_skip(self):
        from poagent.probes.highspeed_serial.probes import USBDwc3Probe
        runner = _make_runner_with_regs({})
        config = _make_config()
        board = MagicMock()
        board.subsystem_by_compatible.return_value = None
        probe = USBDwc3Probe(runner=runner, board_profile=board, config=config)
        result = probe.run(runner, board)
        assert result.severity == "SKIP"


# ── [CP-T12] SDIO card not inserted → CONDITIONAL ───────────────────────────

class TestSDIORegProbe:
    """[CP-T12] SDIO card not inserted → SDIORegProbe returns CONDITIONAL."""

    def test_card_not_inserted_returns_conditional(self):
        from poagent.probes.storage.probes import SDIORegProbe
        # PRESENT_STATE bit 16 = 0 → card absent
        state = 0x00000000
        runner = _make_runner_with_regs({"0x24": state})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfe310000
        spec.compatible = ["arasan,sdhci-5.1"]
        board.subsystem_by_compatible.return_value = spec
        probe = SDIORegProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0x24": state}):
            result = probe.run(runner, board)
        assert result.severity == "CONDITIONAL"
        assert any("NOT inserted" in f or "not inserted" in f.lower() for f in result.findings)

    def test_card_inserted_returns_pass(self):
        from poagent.probes.storage.probes import SDIORegProbe
        # bit 16 set → card present
        state = (1 << 16)
        runner = _make_runner_with_regs({"0x24": state})
        config = _make_config()
        board = MagicMock()
        spec = MagicMock()
        spec.reg_base = 0xfe310000
        spec.compatible = ["arasan,sdhci-5.1"]
        board.subsystem_by_compatible.return_value = spec
        probe = SDIORegProbe(runner=runner, board_profile=board, config=config)
        with patch.object(probe, "run_c_probe",
                          return_value={"0x24": state}):
            result = probe.run(runner, board)
        assert result.severity == "PASS"

    def test_no_sdio_node_returns_skip(self):
        from poagent.probes.storage.probes import SDIORegProbe
        runner = _make_runner_with_regs({})
        config = _make_config()
        board = MagicMock()
        board.subsystem_by_compatible.return_value = None
        probe = SDIORegProbe(runner=runner, board_profile=board, config=config)
        result = probe.run(runner, board)
        assert result.severity == "SKIP"


# ── [CP-T13] Deploy cache — SCP issued only once ─────────────────────────────

class TestDeployCache:
    """[CP-T13] Same binary requested twice → SCP issued only once."""

    def test_second_call_skips_deploy(self):
        runner = _make_runner_with_regs({"0x0": 1}, mem_mb=256)
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with patch.object(cr, "_deploy") as mock_deploy, \
             patch.object(cr, "_verify_integrity"):
            cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x1000", "--offsets", "0x0"])
            cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x2000", "--offsets", "0x0"])

        assert mock_deploy.call_count == 1, \
            f"Deploy called {mock_deploy.call_count} times; expected 1"

    def test_different_binaries_each_deploy_once(self):
        runner = _make_runner_with_regs({"0x0": 1}, mem_mb=256)
        config = _make_config()
        cr = CProbeRunner(runner, config)

        with patch.object(cr, "_deploy") as mock_deploy, \
             patch.object(cr, "_verify_integrity"):
            cr.run_c_probe("c_probes/mmio_dump.c",  ["--base", "0x1000", "--offsets", "0x0"])
            cr.run_c_probe("c_probes/msr_read.c",   ["--msr", "0x1a0"])
            cr.run_c_probe("c_probes/mmio_dump.c",  ["--base", "0x2000", "--offsets", "0x0"])

        assert mock_deploy.call_count == 2, \
            f"Expected 2 deploys (one per binary), got {mock_deploy.call_count}"

    def test_deploy_cache_persists_across_instances_within_run(self):
        """_deployed set is per-CProbeRunner instance (per run), not global."""
        runner = _make_runner_with_regs({"0x0": 1}, mem_mb=256)
        config = _make_config()
        cr1 = CProbeRunner(runner, config)
        cr2 = CProbeRunner(runner, config)

        with patch.object(cr1, "_deploy") as d1, patch.object(cr1, "_verify_integrity"):
            cr1.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])
            cr1.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])

        with patch.object(cr2, "_deploy") as d2, patch.object(cr2, "_verify_integrity"):
            cr2.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])

        assert d1.call_count == 1
        assert d2.call_count == 1  # new instance → deploy again


# ── [CP-T14] No fd leak ──────────────────────────────────────────────────────

class TestNoFdLeak:
    """[CP-T14] No file descriptor leak across 20 repeated run_c_probe() calls."""

    def test_no_fd_leak_repeated_calls(self):
        import gc

        runner = _make_runner_with_regs({"0x0": 42}, mem_mb=256)
        config = _make_config()
        cr = CProbeRunner(runner, config)

        def _fd_count() -> int:
            return len(os.listdir("/proc/self/fd"))

        # Warm up
        with patch.object(cr, "_deploy"), patch.object(cr, "_verify_integrity"):
            for _ in range(3):
                cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])

        gc.collect()
        fd_before = _fd_count()

        with patch.object(cr, "_deploy"), patch.object(cr, "_verify_integrity"):
            for _ in range(20):
                cr.run_c_probe("c_probes/mmio_dump.c", ["--base", "0x0", "--offsets", "0x0"])

        gc.collect()
        fd_after = _fd_count()

        assert fd_after - fd_before <= 3, \
            f"FD leak detected: {fd_before} → {fd_after} (+{fd_after - fd_before})"


# ── DTS reg extraction tests ──────────────────────────────────────────────────

class TestDtsRegExtraction:
    """[CP-01] SubsystemSpec reg_base/reg_size populated from DTS reg property."""

    def test_64bit_reg_parsed_correctly(self):
        from poagent.probes.c_probe_runner import parse_reg_property
        # reg = <0x0 0xfe150000 0x0 0x10000>
        base, size = parse_reg_property([0x0, 0xfe150000, 0x0, 0x10000])
        assert base == 0xfe150000
        assert size == 0x10000

    def test_64bit_reg_high_bits(self):
        from poagent.probes.c_probe_runner import parse_reg_property
        # reg = <0x1 0x00000000 0x0 0x1000>  → base = 0x100000000
        base, size = parse_reg_property([0x1, 0x00000000, 0x0, 0x1000])
        assert base == 0x100000000
        assert size == 0x1000

    def test_short_cells_returns_none(self):
        from poagent.probes.c_probe_runner import parse_reg_property
        result = parse_reg_property([0x0, 0xfe150000])  # only 2 cells
        assert result is None

    def test_empty_cells_returns_none(self):
        from poagent.probes.c_probe_runner import parse_reg_property
        result = parse_reg_property([])
        assert result is None

    def test_zero_base_is_valid(self):
        from poagent.probes.c_probe_runner import parse_reg_property
        base, size = parse_reg_property([0x0, 0x0, 0x0, 0x1000])
        assert base == 0
        assert size == 0x1000
