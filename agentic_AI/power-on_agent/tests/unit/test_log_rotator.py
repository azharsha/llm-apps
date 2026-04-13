"""Tests for security/log_rotator.py.

Critical constraints under test:
- [FINAL-H2] Two-pass rotation: age pass (retention_days) then size pass (max_total_mb)
- Active file protection: run dirs with recently-accessed files skipped in size pass
- size_rotation_exempt=True skips size pass entirely
- retention_days=0 disables age deletion (ISO 26262 compliance)
- rotate_logs() works on subdirectories of log_root (not files directly)
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from poagent.security.log_rotator import rotate_logs


def _make_run_dir(parent: Path, name: str, size_bytes: int, mtime_ago_s: float = 0) -> Path:
    """Create a run subdirectory with a file inside, and set mtime."""
    run_dir = parent / name
    run_dir.mkdir()
    data_file = run_dir / "board_commands.jsonl"
    data_file.write_bytes(b"X" * size_bytes)
    if mtime_ago_s > 0:
        old_time = time.time() - mtime_ago_s
        os.utime(run_dir, (old_time, old_time))
        os.utime(data_file, (old_time, old_time))
    return run_dir


class TestAgeBasedRotation:
    """Age-pass: delete run dirs older than retention_days."""

    def test_old_run_dir_deleted(self, tmp_dir):
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        old_run = _make_run_dir(log_root, "run_old", 100, mtime_ago_s=40 * 86400)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=30,
            max_total_mb=500,
        )

        assert not old_run.exists()
        assert result["age_deleted"] >= 1

    def test_recent_run_dir_kept(self, tmp_dir):
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        recent_run = _make_run_dir(log_root, "run_recent", 100, mtime_ago_s=5 * 86400)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=30,
            max_total_mb=500,
        )

        assert recent_run.exists()
        assert result["age_deleted"] == 0

    def test_retention_days_zero_disables_age_deletion(self, tmp_dir):
        """[ISO 26262] retention_days=0 → no age-based deletion."""
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        old_run = _make_run_dir(log_root, "ancient_run", 100, mtime_ago_s=365 * 86400)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=0,
            max_total_mb=500,
        )

        # retention_days=0 means disable age-based → dir should still exist
        assert old_run.exists()
        assert result["age_deleted"] == 0


class TestSizeBasedRotation:
    """Size-pass: delete oldest dirs until total < max_total_mb."""

    def test_size_exceeded_deletes_oldest(self, tmp_dir):
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        # Two 3MB dirs → 6MB total; max=4MB → oldest should be deleted
        # old_run must be older than active_atime_window_s (3600s) to not be protected
        old_run = _make_run_dir(log_root, "run_old", 3 * 1024 * 1024, mtime_ago_s=7200)
        new_run = _make_run_dir(log_root, "run_new", 3 * 1024 * 1024, mtime_ago_s=10)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=4,
        )

        assert not old_run.exists()
        assert new_run.exists()
        assert result["size_deleted"] >= 1

    def test_size_within_limit_no_deletion(self, tmp_dir):
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        small_run = _make_run_dir(log_root, "small_run", 100, mtime_ago_s=100)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=500,
        )

        assert small_run.exists()
        assert result["size_deleted"] == 0

    def test_size_rotation_exempt_skips_size_pass(self, tmp_dir):
        """size_rotation_exempt=True → size pass entirely skipped."""
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        big_run = _make_run_dir(log_root, "huge_run", 10 * 1024 * 1024, mtime_ago_s=100)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=1,  # would normally trigger deletion
            size_rotation_exempt=True,
        )

        # Size pass skipped → dir not deleted
        assert big_run.exists()
        assert result["size_deleted"] == 0


class TestActiveFileProtection:
    """Active atime protection: recently accessed dirs skipped in size pass."""

    def test_recently_accessed_dir_protected(self, tmp_dir):
        """Dir with file accessed within active_atime_window_s is kept."""
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        active_run = log_root / "active_run"
        active_run.mkdir()
        active_file = active_run / "data.jsonl"
        active_file.write_bytes(b"X" * (5 * 1024 * 1024))
        # Touch atime to "now"
        os.utime(active_file, None)
        os.utime(active_run, None)

        old_run = _make_run_dir(log_root, "old_run", 2 * 1024 * 1024, mtime_ago_s=7200)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=365,
            max_total_mb=4,
            active_atime_window_s=3600,
        )

        # Old dir deleted, active dir kept
        assert not old_run.exists()
        assert active_run.exists()

    def test_current_run_dir_never_deleted(self, tmp_dir):
        """current_run_dir is never deleted even if over size limit."""
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        current_run = _make_run_dir(log_root, "current", 10 * 1024 * 1024, mtime_ago_s=100)

        result = rotate_logs(
            log_root=str(log_root),
            retention_days=1,  # age would delete it
            max_total_mb=1,    # size would delete it
            current_run_dir=str(current_run),
        )

        # Should NOT be deleted since it's the current run
        assert current_run.exists()


class TestReturnValue:
    """rotate_logs() returns dict with age_deleted, size_deleted, bytes_freed, errors."""

    def test_returns_dict_with_required_keys(self, tmp_dir):
        log_root = tmp_dir / "logs"
        log_root.mkdir()

        result = rotate_logs(str(log_root), retention_days=30, max_total_mb=100)

        assert isinstance(result, dict)
        assert "age_deleted" in result
        assert "size_deleted" in result
        assert "bytes_freed" in result
        assert "errors" in result

    def test_nonexistent_root_returns_zeros(self, tmp_dir):
        result = rotate_logs(
            str(tmp_dir / "nonexistent"),
            retention_days=30,
            max_total_mb=100,
        )
        assert result["age_deleted"] == 0
        assert result["size_deleted"] == 0
