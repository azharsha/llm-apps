"""LogRotator — two-pass log retention enforcement.

[LOG-01] Pass 1: age-based deletion (files older than log_retention_days).
[LOG-02] Pass 2: size-based deletion (oldest first until under log_max_total_mb).
         Skipped entirely when log_size_rotation_exempt=True.
[LOG-03] Active atime protection: files accessed within log_active_atime_window_s
         are exempt from deletion in both passes.

Run order: age pass → size pass. Never deletes the active run's own log dir.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


def rotate_logs(
    log_root: str,
    retention_days: int,
    max_total_mb: float,
    size_rotation_exempt: bool = False,
    active_atime_window_s: int = 3600,
    current_run_dir: Optional[str] = None,
) -> dict:
    """Two-pass log rotation for the poagent log directory.

    Args:
        log_root: Root directory containing per-run subdirectories.
        retention_days: Delete run dirs older than this many days.
        max_total_mb: Maximum total log storage in MB (size pass).
        size_rotation_exempt: If True, skip the size pass entirely.
        active_atime_window_s: Exempt files accessed within this window (seconds).
        current_run_dir: Absolute path of current run dir — never deleted.

    Returns:
        dict with keys: age_deleted, size_deleted, bytes_freed, errors
    """
    root = Path(log_root)
    if not root.exists():
        log.debug("log_root_not_found", path=log_root)
        return {"age_deleted": 0, "size_deleted": 0, "bytes_freed": 0, "errors": []}

    now = time.time()
    # retention_days=0 disables age-based deletion (ISO 26262 compliance)
    age_pass_enabled = retention_days > 0
    cutoff_age = now - (retention_days * 86400)
    atime_cutoff = now - active_atime_window_s

    age_deleted = 0
    size_deleted = 0
    bytes_freed = 0
    errors: list[str] = []

    # Collect all run directories (immediate children only)
    run_dirs = sorted(
        [d for d in root.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
    )

    def _is_active(d: Path) -> bool:
        """True if the directory was recently accessed or is the current run."""
        if current_run_dir and str(d.resolve()) == str(Path(current_run_dir).resolve()):
            return True
        try:
            # Check most recently accessed file in the directory
            for child in d.rglob("*"):
                if child.is_file():
                    try:
                        if child.stat().st_atime > atime_cutoff:
                            return True
                    except OSError:
                        pass
        except Exception:
            pass
        return False

    def _dir_size_bytes(d: Path) -> int:
        """Total size of all files under d."""
        total = 0
        try:
            for child in d.rglob("*"):
                if child.is_file():
                    try:
                        total += child.stat().st_size
                    except OSError:
                        pass
        except Exception:
            pass
        return total

    # ── Pass 1: Age-based deletion ────────────────────────────────────────
    remaining_dirs: list[Path] = []
    for run_dir in run_dirs:
        try:
            mtime = run_dir.stat().st_mtime
            if age_pass_enabled and mtime < cutoff_age and not _is_active(run_dir):
                size = _dir_size_bytes(run_dir)
                _rmtree(run_dir, errors)
                age_deleted += 1
                bytes_freed += size
                log.info("log_age_deleted", path=str(run_dir),
                         age_days=round((now - mtime) / 86400, 1))
            else:
                remaining_dirs.append(run_dir)
        except Exception as exc:
            errors.append(f"age_pass error {run_dir}: {exc}")
            remaining_dirs.append(run_dir)

    # ── Pass 2: Size-based deletion ───────────────────────────────────────
    if not size_rotation_exempt:
        # Recompute total size of remaining dirs
        total_bytes = sum(_dir_size_bytes(d) for d in remaining_dirs)
        max_bytes = int(max_total_mb * 1_048_576)

        # Sort oldest first for deletion
        remaining_dirs.sort(key=lambda d: d.stat().st_mtime)
        for run_dir in remaining_dirs:
            if total_bytes <= max_bytes:
                break
            if _is_active(run_dir):
                continue
            try:
                size = _dir_size_bytes(run_dir)
                _rmtree(run_dir, errors)
                total_bytes -= size
                size_deleted += 1
                bytes_freed += size
                log.info("log_size_deleted", path=str(run_dir),
                         freed_mb=round(size / 1_048_576, 2),
                         total_mb=round(total_bytes / 1_048_576, 2))
            except Exception as exc:
                errors.append(f"size_pass error {run_dir}: {exc}")

    log.info(
        "log_rotation_complete",
        age_deleted=age_deleted,
        size_deleted=size_deleted,
        bytes_freed_mb=round(bytes_freed / 1_048_576, 2),
        errors=len(errors),
    )

    return {
        "age_deleted": age_deleted,
        "size_deleted": size_deleted,
        "bytes_freed": bytes_freed,
        "errors": errors,
    }


def _rmtree(path: Path, errors: list[str]) -> None:
    """Recursively remove a directory tree, collecting errors."""
    import shutil
    try:
        shutil.rmtree(str(path))
    except Exception as exc:
        errors.append(f"rmtree failed {path}: {exc}")
