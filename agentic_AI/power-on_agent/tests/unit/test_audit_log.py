"""Tests for security/audit_log.py.

Critical constraints under test:
- [N-PG-06] Every SSH exec logged as JSONL with timestamp, command, stdout hash, returncode
- [H-01] CommandLogEntry has board_name, run_id fields
- Thread-safe writes (Lock)
- read_entries() returns valid CommandLogEntry list
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest


class TestBoardCommandLog:
    def test_log_creates_file(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(
            run_dir=str(tmp_dir),
            board_name="test-board",
            run_id="run-001",
        )
        log.append(
            domain="power_clocking",
            probe="RailVoltageProbe",
            transport="ssh",
            command="echo hello",
            stdout_sha256=hashlib.sha256(b"hello\n").hexdigest(),
            stdout_len=6,
            returncode=0,
            duration_ms=50,
        )
        log.close()

        log_file = tmp_dir / "board_commands.jsonl"
        assert log_file.exists()

    def test_log_entry_is_valid_json(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="board1", run_id="r1")
        log.append(
            domain="compute_memory",
            probe="CPUInfoProbe",
            transport="ssh",
            command="uname -r",
            stdout_sha256=hashlib.sha256(b"5.15.0\n").hexdigest(),
            stdout_len=7,
            returncode=0,
            duration_ms=30,
        )
        log.close()

        log_file = tmp_dir / "board_commands.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "command" in entry
        assert "returncode" in entry
        assert "timestamp" in entry

    def test_log_entry_has_required_fields(self, tmp_dir):
        """[H-01] board_name, run_id must be present."""
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="my-board", run_id="abc-123")
        log.append(
            domain="storage",
            probe="NVMeProbe",
            transport="ssh",
            command="cat /proc/version",
            stdout_sha256=hashlib.sha256(b"Linux\n").hexdigest(),
            stdout_len=6,
            returncode=0,
            duration_ms=20,
        )
        log.close()

        log_file = tmp_dir / "board_commands.jsonl"
        entry = json.loads(log_file.read_text().strip())
        assert entry.get("board_name") == "my-board"
        assert entry.get("run_id") == "abc-123"

    def test_log_entry_has_stdout_sha256(self, tmp_dir):
        """[N-PG-06] stdout hash stored (SHA-256), not raw stdout."""
        from poagent.security.audit_log import BoardCommandLog

        stdout = b"hello world\n"
        expected_hash = hashlib.sha256(stdout).hexdigest()

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="b", run_id="r")
        log.append(
            domain="audio",
            probe="ALSAProbe",
            transport="ssh",
            command="echo 'hello world'",
            stdout_sha256=expected_hash,
            stdout_len=len(stdout),
            returncode=0,
            duration_ms=10,
        )
        log.close()

        log_file = tmp_dir / "board_commands.jsonl"
        entry = json.loads(log_file.read_text().strip())
        assert entry.get("stdout_sha256") == expected_hash

    def test_multiple_records_appended(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="b", run_id="r")
        for i, cmd in enumerate(["cmd1", "cmd2"]):
            log.append(
                domain="networking",
                probe="EthernetProbe",
                transport="ssh",
                command=cmd,
                stdout_sha256=hashlib.sha256(f"out{i}".encode()).hexdigest(),
                stdout_len=4,
                returncode=i,
                duration_ms=10,
            )
        log.close()

        log_file = tmp_dir / "board_commands.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["command"] == "cmd1"
        assert json.loads(lines[1])["command"] == "cmd2"

    def test_thread_safe_concurrent_writes(self, tmp_dir):
        """Multiple threads writing should not corrupt the log."""
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="b", run_id="r")
        errors = []

        def write_n(thread_name: str, n: int) -> None:
            try:
                for i in range(n):
                    log.append(
                        domain="sensors_misc",
                        probe="ThermalZoneProbe",
                        transport="ssh",
                        command=f"cmd-{thread_name}-{i}",
                        stdout_sha256=hashlib.sha256(b"").hexdigest(),
                        stdout_len=0,
                        returncode=0,
                        duration_ms=5,
                    )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_n, args=(f"t{j}", 10))
            for j in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        log.close()

        assert not errors

        log_file = tmp_dir / "board_commands.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 50  # 5 threads × 10 writes each

        for line in lines:
            json.loads(line)  # All lines must be valid JSON


class TestReadEntries:
    def test_read_entries_returns_list(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="b", run_id="r")
        log.append(
            domain="security_crypto",
            probe="TRNGProbe",
            transport="ssh",
            command="ls /",
            stdout_sha256=hashlib.sha256(b"bin etc\n").hexdigest(),
            stdout_len=8,
            returncode=0,
            duration_ms=15,
        )

        entries = log.read_entries()
        assert isinstance(entries, list)
        assert len(entries) == 1
        log.close()

    def test_read_entries_fields(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="x", run_id="y")
        log.append(
            domain="display_graphics",
            probe="DRMProbe",
            transport="ssh",
            command="dmesg",
            stdout_sha256=hashlib.sha256(b"log").hexdigest(),
            stdout_len=3,
            returncode=0,
            duration_ms=100,
        )

        entries = log.read_entries()
        entry = entries[0]
        assert entry.command == "dmesg"
        assert entry.board_name == "x"
        assert entry.run_id == "y"
        log.close()

    def test_entry_count_property(self, tmp_dir):
        from poagent.security.audit_log import BoardCommandLog

        log = BoardCommandLog(run_dir=str(tmp_dir), board_name="b", run_id="r")
        assert log.entry_count == 0

        log.append(
            domain="lowspeed_interface",
            probe="I2CProbe",
            transport="ssh",
            command="i2cdetect -l",
            stdout_sha256=hashlib.sha256(b"i2c-0").hexdigest(),
            stdout_len=5,
            returncode=0,
            duration_ms=200,
        )
        assert log.entry_count == 1
        log.close()
