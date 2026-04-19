"""
input_handler.py — Phase 1
Single entry point for all log ingestion. Handles files, stdin, compression,
UTF-8 sanitisation, streaming, and container log detection.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator

__all__ = ["open_log", "InputError", "InputMetadata", "LogLineIterator"]

# ── Public constants ──────────────────────────────────────────────────────────

STREAM_THRESHOLD_MB: float = 100.0
SUPPORTED_COMPRESSIONS: tuple[str, ...] = (".gz", ".bz2", ".xz")
# Compiled at module load time — re.search(pattern, line) inside _detect_container
# is called for every file; pre-compilation avoids repeated re.compile() overhead.
CONTAINER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^[A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2} .+ systemd"), "systemd-journal"),
    (re.compile(r'^time="\d{4}-\d{2}-\d{2}T'),                          "docker"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z .+k8s"), "containerd"),
]

LogLineIterator = Iterator[str]

# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class InputMetadata:
    source_path:      str           # original path or "<stdin>"
    compression:      str | None    # "gz" | "bz2" | "xz" | None
    encoding_errors:  int           # count of bytes replaced with U+FFFD
    is_streamed:      bool          # True if file > STREAM_THRESHOLD or stdin
    is_container_log: bool          # True if journald/docker/containerd prefix detected
    container_hint:   str | None    # "docker" | "containerd" | "systemd-journal" | None
    line_count:       int           # total lines yielded (filled after iteration)
    size_bytes:       int           # raw file size in bytes (0 for stdin)


@dataclass
class InputError(Exception):
    code:    str     # "EC-10" | "EC-03" | "EC-06-TIMEOUT" | "EC-INPUT"
    message: str
    source:  str     # path or "<stdin>"
    detail:  str = ""

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str]:
        return {
            "error":   self.code,
            "message": self.message,
            "source":  self.source,
            "detail":  self.detail,
        }


# ── Public entry point ────────────────────────────────────────────────────────


def open_log(
    source: str | Path,
    *,
    encoding: str = "utf-8",
    stream_threshold_mb: float = STREAM_THRESHOLD_MB,
    force_encoding_errors: str = "replace",
) -> tuple[LogLineIterator, InputMetadata]:
    """
    Open any log source and return a clean line iterator + metadata.

    Handles:
      - Plain files, Path objects, "-" (stdin)
      - .gz / .bz2 / .xz auto-decompression         (EC-12)
      - Files > stream_threshold_mb streamed          (EC-06)
      - Non-UTF8 bytes replaced with U+FFFD           (EC-03)
      - Empty files raise InputError(code="EC-10")    (EC-10)
      - Container/VM log prefixes detected            (EC-11)

    Returns:
      (iterator_of_clean_lines, InputMetadata)

    Raises:
      InputError        — all unrecoverable input problems
      FileNotFoundError — if path does not exist
    """
    if _is_stdin(source):
        raw_stream:  IO[bytes] = sys.stdin.buffer
        size_bytes:  int       = 0
        src_str:     str       = "<stdin>"
        compression: str | None = None
    else:
        path = Path(source).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Log not found: {path}")
        size_bytes  = _get_file_size(path)
        if size_bytes == 0:
            raise InputError(
                code    = "EC-10",
                message = "Empty input — no log content to analyse",
                source  = str(path),
                detail  = "File exists but contains 0 bytes",
            )
        compression = _detect_compression(path)
        raw_stream  = _open_raw_stream(path, compression)
        src_str     = str(path)

    meta = InputMetadata(
        source_path      = src_str,
        compression      = compression,
        encoding_errors  = 0,
        is_streamed      = (
            size_bytes == 0                                   # stdin
            or size_bytes > stream_threshold_mb * 1024 ** 2  # large plain file
            or compression is not None                        # compressed — uncompressed size unknown
        ),
        is_container_log = False,
        container_hint   = None,
        line_count       = 0,
        size_bytes       = size_bytes,
    )

    return _line_generator(raw_stream, meta, encoding, force_encoding_errors), meta


# ── Private helpers ───────────────────────────────────────────────────────────


def _is_stdin(source: str | Path) -> bool:
    return str(source) == "-"


def _get_file_size(path: Path) -> int:
    return path.stat().st_size


def _detect_compression(path: Path) -> str | None:
    name = path.name.lower()
    if name.endswith(".gz"):
        return "gz"
    if name.endswith(".bz2"):
        return "bz2"
    if name.endswith(".xz"):
        return "xz"
    return None


def _open_raw_stream(path: Path, compression: str | None) -> IO[bytes]:
    if compression == "gz":
        return gzip.open(path, "rb")  # type: ignore[return-value]
    if compression == "bz2":
        return bz2.open(path, "rb")
    if compression == "xz":
        return lzma.open(path, "rb")
    return open(path, "rb")


def _sanitize_line(
    raw: bytes,
    error_counts: list[int],
    error_mode: str,
    source: str,
) -> str:
    """Decode raw bytes to UTF-8, replacing or erroring on invalid sequences."""
    # Replace null bytes — invalid in UTF-8 log context
    raw = raw.replace(b"\x00", b"\xff")

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        if error_mode == "strict":
            raise InputError(
                code    = "EC-03",
                message = "Non-UTF8 byte encountered",
                source  = source,
                detail  = f"offset={exc.start}: {exc.reason}",
            ) from exc
        decoded = raw.decode("utf-8", errors="replace")
        error_counts[0] += decoded.count("\ufffd")
        return decoded


def _detect_container(first_lines: list[str]) -> tuple[bool, str | None]:
    """Scan first lines for container/VM log prefixes."""
    for line in first_lines:
        for pattern, hint in CONTAINER_PATTERNS:
            if pattern.search(line):
                return True, hint
    return False, None


def _line_generator(
    raw_stream: IO[bytes],
    meta: InputMetadata,
    encoding: str,
    error_mode: str,
) -> Iterator[str]:
    """Core generator: yields clean UTF-8 lines, updates metadata in place."""
    error_counts:      list[int]  = [0]
    first_lines:       list[str]  = []
    container_checked: bool       = False

    for raw_line in raw_stream:
        line = _sanitize_line(raw_line, error_counts, error_mode, meta.source_path)
        line = line.rstrip("\r\n")

        if not container_checked and len(first_lines) < 20:
            first_lines.append(line)
            if len(first_lines) == 20:
                meta.is_container_log, meta.container_hint = _detect_container(first_lines)
                container_checked = True

        meta.line_count      += 1
        meta.encoding_errors  = error_counts[0]
        yield line

    # Handle files with fewer than 20 lines
    if not container_checked and first_lines:
        meta.is_container_log, meta.container_hint = _detect_container(first_lines)
