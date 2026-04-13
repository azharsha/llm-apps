"""BoardCommandLog — JSONL audit log of every command run on the target board.

Each entry is a JSON object on a single line (JSONL format).
The log is written to <run_dir>/board_commands.jsonl.

Thread-safe: all writes are protected by a threading.Lock.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass
class CommandLogEntry:
    """Single entry in the BoardCommandLog."""
    timestamp: float
    run_id: str
    board_name: str
    domain: str
    probe: str
    transport: str   # "ssh" | "serial"
    command: str
    returncode: int
    stdout_sha256: str
    stdout_len: int
    duration_ms: int
    timed_out: bool = False


class BoardCommandLog:
    """Thread-safe JSONL audit log.

    Usage:
        audit_log = BoardCommandLog(run_dir="/var/log/poagent/run_001",
                                    run_id="run_001", board_name="tgl-mb")
        with audit_log:
            ...
        # or call close() explicitly
    """

    def __init__(
        self,
        run_dir: str,
        run_id: str,
        board_name: str,
    ) -> None:
        self._run_id = run_id
        self._board_name = board_name
        self._lock = threading.Lock()
        self._path = Path(run_dir) / "board_commands.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")
        self._count = 0
        log.debug("audit_log_opened", path=str(self._path))

    def append(
        self,
        domain: str,
        probe: str,
        transport: str,
        command: str,
        returncode: int,
        stdout_sha256: str,
        stdout_len: int,
        duration_ms: int,
        timed_out: bool = False,
    ) -> None:
        """Append a command entry to the audit log. Thread-safe."""
        entry = CommandLogEntry(
            timestamp=time.time(),
            run_id=self._run_id,
            board_name=self._board_name,
            domain=domain,
            probe=probe,
            transport=transport,
            command=command,
            returncode=returncode,
            stdout_sha256=stdout_sha256,
            stdout_len=stdout_len,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
        line = json.dumps(asdict(entry))
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()
            self._count += 1

    @property
    def entry_count(self) -> int:
        return self._count

    @property
    def path(self) -> str:
        return str(self._path)

    def close(self) -> None:
        """Flush and close the log file."""
        with self._lock:
            try:
                self._fh.flush()
                self._fh.close()
            except Exception as exc:
                log.warning("audit_log_close_failed", error=str(exc))
        log.debug("audit_log_closed", path=str(self._path), entries=self._count)

    def __enter__(self) -> "BoardCommandLog":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read_entries(self) -> list[CommandLogEntry]:
        """Read all entries from the log file. For post-run analysis."""
        return read_entries(self._path)


def read_entries(log_path: "str | Path") -> list[CommandLogEntry]:
    """Read all CommandLogEntry records from a JSONL log file.

    Standalone function for use in post-run analysis without a BoardCommandLog instance.
    Returns empty list if file does not exist or cannot be read.
    """
    entries: list[CommandLogEntry] = []
    path = Path(log_path)
    if not path.exists():
        return entries
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    entries.append(CommandLogEntry(**d))
    except Exception as exc:
        log.warning("audit_log_read_failed", error=str(exc))
    return entries
