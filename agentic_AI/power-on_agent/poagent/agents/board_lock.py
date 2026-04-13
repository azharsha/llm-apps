"""Board exclusion group lock — prevents concurrent runs on same board.

[N-OPS-03] A board can only be in one active run at a time.
The lock is implemented as a file lock under:
  <lock_dir>/<board_name>.lock

acquire_board_lock() must be called before any transport connection.
The lock is automatically released on close() or context exit.

acquire(timeout): timeout = max_run_time_s + 10 (extra buffer).
If acquisition times out, raises BoardLockError — the board is busy.
"""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_LOCK_DIR = "/var/lock/poagent"


class BoardLockError(Exception):
    """Raised when a board lock cannot be acquired."""


class BoardLock:
    """File-based exclusive board lock.

    Usage:
        lock = BoardLock(board_name="tgl-mb", lock_dir="/var/lock/poagent")
        with lock.acquire(timeout=3610):
            # board is exclusively ours
            ...
        # lock auto-released on exit
    """

    def __init__(
        self,
        board_name: str,
        lock_dir: str = _DEFAULT_LOCK_DIR,
        run_id: str = "",
    ) -> None:
        self._board_name = board_name
        self._lock_dir = Path(lock_dir)
        self._run_id = run_id
        self._lock_path = self._lock_dir / f"{board_name}.lock"
        self._fh: Optional[object] = None
        self._acquired = False

    def acquire(self, timeout: float = 3610.0) -> "BoardLock":
        """Acquire exclusive lock. Blocks up to timeout seconds.

        Raises BoardLockError if timeout expires.
        """
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        self._fh = open(self._lock_path, "w")  # noqa: WPS515 (open for lock, not read)

        log.debug("board_lock_acquiring", board=self._board_name, timeout=timeout)
        while True:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[arg-type]
                self._acquired = True
                # Write run_id to lock file for diagnostics
                self._fh.write(f"run_id={self._run_id}\npid={os.getpid()}\n")  # type: ignore[union-attr]
                self._fh.flush()  # type: ignore[union-attr]
                log.info("board_lock_acquired", board=self._board_name, run_id=self._run_id)
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    try:
                        self._fh.close()  # type: ignore[union-attr]
                    except Exception:
                        pass
                    # Read existing lock file to identify who holds it
                    owner_info = _read_lock_owner(self._lock_path)
                    raise BoardLockError(
                        f"Board '{self._board_name}' is locked by another run. "
                        f"Lock file: {self._lock_path}. "
                        f"Owner: {owner_info}. "
                        f"Timed out after {timeout}s."
                    )
                time.sleep(1.0)

    def release(self) -> None:
        """Release the board lock."""
        if self._fh is not None:
            try:
                if self._acquired:
                    fcntl.flock(self._fh, fcntl.LOCK_UN)  # type: ignore[arg-type]
                self._fh.close()  # type: ignore[union-attr]
            except Exception as exc:
                log.warning("board_lock_release_error", board=self._board_name, error=str(exc))
            finally:
                self._fh = None
                self._acquired = False
            log.info("board_lock_released", board=self._board_name)
        # Clean up lock file
        try:
            self._lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    def __enter__(self) -> "BoardLock":
        return self

    def __exit__(self, *args: object) -> None:
        self.release()

    @property
    def is_acquired(self) -> bool:
        return self._acquired


def acquire_board_lock(
    board_name: str,
    max_run_time_s: float,
    run_id: str = "",
    lock_dir: str = _DEFAULT_LOCK_DIR,
) -> BoardLock:
    """Convenience function: create and acquire a BoardLock.

    timeout = max_run_time_s + 10 (extra buffer as per [N-OPS-03]).
    """
    lock = BoardLock(board_name=board_name, lock_dir=lock_dir, run_id=run_id)
    lock.acquire(timeout=max_run_time_s + 10)
    return lock


def _read_lock_owner(lock_path: Path) -> str:
    """Read contents of lock file for diagnostic info."""
    try:
        return lock_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return "unknown"
