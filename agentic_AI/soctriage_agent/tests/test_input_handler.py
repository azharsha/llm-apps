"""
Phase 1 — Input Handler Tests
Expected: 28 PASSED, 0 FAILED, 0 ERROR
"""

import gzip, bz2, lzma, os, sys, pytest, resource
from pathlib import Path
from soctriage.core.input_handler import open_log, InputError, InputMetadata

FIXTURES = Path("tests/fixtures")


# ── FR-01/02/03: Source type acceptance ──────────────────────────────────────

def test_open_log_accepts_str_path():
    it, meta = open_log(str(FIXTURES / "generic/normal_dmesg.log"))
    lines = list(it)
    assert len(lines) > 0
    assert meta.source_path.endswith("normal_dmesg.log")

def test_open_log_accepts_path_object():
    it, meta = open_log(FIXTURES / "generic/normal_dmesg.log")
    assert list(it)

def test_open_log_accepts_stdin(monkeypatch, tmp_path):
    fake_log = tmp_path / "fake.log"
    fake_log.write_text("kernel: [    0.000000] Booting Linux\n")
    with open(fake_log, "rb") as fh:
        class _FakeStdin:
            buffer = fh
        monkeypatch.setattr(sys, "stdin", _FakeStdin())
        it, meta = open_log("-")
        lines = list(it)
    assert len(lines) >= 1
    assert meta.source_path == "<stdin>"

def test_open_log_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        open_log("/nonexistent/path/crash.log")


# ── EC-10: Empty file ────────────────────────────────────────────────────────

def test_ec10_empty_file_raises_input_error():
    with pytest.raises(InputError) as exc_info:
        open_log(FIXTURES / "generic/empty.log")
    assert exc_info.value.code == "EC-10"

def test_ec10_input_error_has_source():
    with pytest.raises(InputError) as exc_info:
        open_log(FIXTURES / "generic/empty.log")
    assert "empty.log" in exc_info.value.source

def test_ec10_input_error_to_dict():
    with pytest.raises(InputError) as exc_info:
        open_log(FIXTURES / "generic/empty.log")
    d = exc_info.value.to_dict()
    assert d["error"] == "EC-10"
    assert "message" in d and "source" in d


# ── EC-03: Binary / non-UTF8 bytes ───────────────────────────────────────────

def test_ec03_binary_file_does_not_crash():
    it, meta = open_log(FIXTURES / "generic/binary_contaminated.log")
    lines = list(it)
    assert len(lines) > 0

def test_ec03_binary_file_tracks_encoding_errors():
    it, meta = open_log(FIXTURES / "generic/binary_contaminated.log")
    list(it)
    assert meta.encoding_errors > 0

def test_ec03_binary_lines_contain_replacement_char():
    it, meta = open_log(FIXTURES / "generic/binary_contaminated.log")
    lines = list(it)
    assert any("\ufffd" in line for line in lines)

def test_ec03_strict_mode_raises_input_error(tmp_path):
    bad_file = tmp_path / "bad.log"
    bad_file.write_bytes(b"good line\nbad \xff\xfe bytes\n")
    with pytest.raises(InputError) as exc_info:
        it, _ = open_log(bad_file, force_encoding_errors="strict")
        list(it)
    assert exc_info.value.code == "EC-03"


# ── EC-12: Compressed file decompression ─────────────────────────────────────

def test_ec12_gz_decompression(tmp_path):
    content = b"kernel: GPU hang detected\n" * 10
    gz_path = tmp_path / "test.log.gz"
    with gzip.open(gz_path, "wb") as fh:
        fh.write(content)
    it, meta = open_log(gz_path)
    lines = list(it)
    assert len(lines) == 10
    assert meta.compression == "gz"

def test_ec12_bz2_decompression(tmp_path):
    content = b"kernel: SMMU fault\n" * 10
    bz2_path = tmp_path / "test.log.bz2"
    with bz2.open(bz2_path, "wb") as fh:
        fh.write(content)
    it, meta = open_log(bz2_path)
    lines = list(it)
    assert len(lines) == 10
    assert meta.compression == "bz2"

def test_ec12_xz_decompression(tmp_path):
    content = b"amdgpu: ring timeout\n" * 10
    xz_path = tmp_path / "test.log.xz"
    with lzma.open(xz_path, "wb") as fh:
        fh.write(content)
    it, meta = open_log(xz_path)
    lines = list(it)
    assert len(lines) == 10
    assert meta.compression == "xz"

def test_ec12_plain_file_has_none_compression():
    it, meta = open_log(FIXTURES / "generic/normal_dmesg.log")
    list(it)
    assert meta.compression is None

def test_ec12_compressed_output_matches_plain(tmp_path):
    content = b"[   0.000000] Linux version 6.8.0\n[   0.001000] Booting\n"
    plain   = tmp_path / "test.log"
    gz_path = tmp_path / "test.log.gz"
    plain.write_bytes(content)
    with gzip.open(gz_path, "wb") as fh:
        fh.write(content)
    plain_lines = list(open_log(plain)[0])
    gz_lines    = list(open_log(gz_path)[0])
    assert plain_lines == gz_lines


# ── EC-06: Large file streaming ──────────────────────────────────────────────

def test_ec06_large_file_streams_not_loads(tmp_path):
    """200MB synthetic log must stream without exceeding 60MB peak RSS."""
    large_gz = tmp_path / "large.log.gz"
    line = b"[12345.678901] amdgpu 0000:03:00.0: ring gfx_0 timeout\n"
    with gzip.open(large_gz, "wb") as fh:
        for _ in range(3_500_000):
            fh.write(line)
    before_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    it, meta  = open_log(large_gz)
    for _ in it:
        pass
    after_kb  = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    delta_mb  = (after_kb - before_kb) / 1024
    assert delta_mb < 60, f"Memory delta too high: {delta_mb:.1f}MB"
    assert meta.is_streamed is True
    assert meta.line_count > 1_000_000

def test_ec06_stdin_always_streamed(monkeypatch, tmp_path):
    fake = tmp_path / "fake.log"
    fake.write_text("line1\nline2\n")
    with open(fake, "rb") as fh:
        class _FakeStdin:
            buffer = fh
        monkeypatch.setattr(sys, "stdin", _FakeStdin())
        it, meta = open_log("-")
        list(it)
    assert meta.is_streamed is True


# ── EC-11: Container / VM log detection ──────────────────────────────────────

def test_ec11_docker_prefix_detected(tmp_path):
    docker_log = tmp_path / "docker.log"
    docker_log.write_text(
        'time="2026-01-01T00:00:00Z" level=info msg="container started"\n' * 25
    )
    it, meta = open_log(docker_log)
    list(it)
    assert meta.is_container_log is True
    assert meta.container_hint   == "docker"

def test_ec11_container_log_still_yields_lines(tmp_path):
    docker_log = tmp_path / "docker.log"
    docker_log.write_text(
        'time="2026-01-01T00:00:00Z" kernel: GPU hang\n' * 5
    )
    it, meta = open_log(docker_log)
    assert len(list(it)) == 5

def test_ec11_plain_dmesg_not_flagged_as_container():
    it, meta = open_log(FIXTURES / "generic/normal_dmesg.log")
    list(it)
    assert meta.is_container_log is False
    assert meta.container_hint   is None


# ── Line normalisation ────────────────────────────────────────────────────────

def test_lines_have_no_trailing_newline(tmp_path):
    f = tmp_path / "newlines.log"
    f.write_bytes(b"line one\r\nline two\nline three\r")
    it, _ = open_log(f)
    for line in it:
        assert not line.endswith("\n")
        assert not line.endswith("\r")

def test_leading_spaces_preserved(tmp_path):
    f = tmp_path / "indented.log"
    f.write_bytes(b"BUG: KASAN\n    at addr 0xffff\n        call trace\n")
    it, _ = open_log(f)
    lines = list(it)
    assert lines[1].startswith("    ")
    assert lines[2].startswith("        ")

def test_empty_lines_yielded(tmp_path):
    f = tmp_path / "gaps.log"
    f.write_bytes(b"line one\n\nline three\n")
    it, _ = open_log(f)
    lines = list(it)
    assert len(lines) == 3
    assert lines[1] == ""


# ── Metadata completeness ─────────────────────────────────────────────────────

def test_metadata_line_count_correct(tmp_path):
    f = tmp_path / "count.log"
    f.write_bytes(b"\n".join(f"line {i}".encode() for i in range(100)))
    it, meta = open_log(f)
    list(it)
    assert meta.line_count == 100

def test_metadata_size_bytes_nonzero():
    it, meta = open_log(FIXTURES / "generic/normal_dmesg.log")
    list(it)
    assert meta.size_bytes > 0
    assert meta.line_count > 0
