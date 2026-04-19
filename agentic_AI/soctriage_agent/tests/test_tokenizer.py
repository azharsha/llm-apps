"""
test_tokenizer.py — Phase 2 v2.0.0
35 tests for the YAML-driven tokenizer.
Expected: 35 PASSED, 0 FAILED
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from soctriage.core.tokenizer import LogToken, tokenize

FIXTURES = Path("tests/fixtures")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lines(text: str):
    for line in text.strip().split("\n"):
        yield line

def _tok(text: str, **kw) -> list[LogToken]:
    return list(tokenize(_lines(text), **kw))


# ── LogToken dataclass ────────────────────────────────────────────────────────

def test_logtoken_has_required_fields():
    t = LogToken(line_no=1, raw="x", token_type="unknown", arch="unknown",
                 chip_gen="unknown", kernel_ver=None, timestamp=None,
                 is_duplicate=False, confidence=0.1)
    assert t.line_no == 1
    assert t.raw == "x"
    assert t.confidence == 0.1

def test_tokenize_returns_generator():
    result = tokenize(iter([]))
    assert isinstance(result, types.GeneratorType)

def test_empty_iterator_yields_nothing():
    assert list(tokenize(iter([]))) == []


# ── Token types from core_kernel.yaml ────────────────────────────────────────

def test_token_type_panic_kernel_panic():
    tokens = _tok("Kernel panic - not syncing: fatal exception")
    assert tokens[0].token_type == "panic"

def test_token_type_panic_null_deref():
    tokens = _tok("BUG: kernel NULL pointer dereference, address: 0x0000")
    assert tokens[0].token_type == "panic"

def test_token_type_oops_header():
    tokens = _tok("Oops: 0002 [#1] SMP KASAN")
    assert tokens[0].token_type == "oops_header"

def test_token_type_oops_unable_to_handle():
    tokens = _tok("Unable to handle kernel NULL pointer dereference at virtual address")
    assert tokens[0].token_type == "oops_header"

def test_token_type_call_trace_header():
    tokens = _tok("Call Trace:")
    assert tokens[0].token_type == "call_trace_header"

def test_token_type_call_trace_frame():
    tokens = _tok("Call Trace:\n [<ffffffff812345>] do_fault+0x4c/0x80")
    assert tokens[1].token_type == "call_trace_frame"

def test_token_type_register_dump_x86():
    tokens = _tok("RIP: 0010:amdgpu_ttm_fault+0x7c/0x180", arch_hint="x86_64")
    assert tokens[0].token_type == "register_dump"

def test_token_type_register_arm64():
    tokens = _tok("pc : adreno_gpu_crash+0x48/0x100", arch_hint="arm64")
    assert tokens[0].token_type == "register_arm64"

def test_token_type_lockup_soft():
    tokens = _tok("watchdog: BUG: soft lockup - CPU#3 stuck for 22s!")
    assert tokens[0].token_type == "lockup_soft"

def test_token_type_lockup_hard():
    tokens = _tok("NMI watchdog: Watchdog detected hard LOCKUP on cpu 1")
    assert tokens[0].token_type == "lockup_hard"

def test_token_type_deadlock():
    tokens = _tok("WARNING: possible circular locking dependency detected")
    assert tokens[0].token_type == "deadlock"

def test_token_type_rcu_stall():
    tokens = _tok("INFO: rcu_sched self-detected stall on CPU")
    assert tokens[0].token_type == "rcu_stall"

def test_token_type_hung_task():
    tokens = _tok("INFO: task kworker:0 blocked for more than 120 seconds.")
    assert tokens[0].token_type == "hung_task"

def test_token_type_stack_overflow():
    tokens = _tok("corrupted stack end detected inside scheduler")
    assert tokens[0].token_type == "stack_overflow"

def test_token_type_warning():
    tokens = _tok("WARNING: CPU: 3 PID: 1234 at drivers/gpu/drm/i915/gt/uc/intel_guc.c:123")
    assert tokens[0].token_type == "warning"

def test_token_type_separator():
    tokens = _tok("---[ cut here ]---")
    assert tokens[0].token_type == "separator"

def test_token_type_info_linux_version():
    tokens = _tok("Linux version 6.8.0-45-generic (buildd@lcy02)")
    assert tokens[0].token_type == "info"

def test_token_type_info_dmesg_bracket():
    tokens = _tok("[    0.000000] Booting Linux kernel")
    assert tokens[0].token_type == "info"

def test_token_type_unknown_fallback():
    tokens = _tok("completely unrecognized log line xyz123")
    assert tokens[0].token_type == "unknown"

def test_confidence_known_type():
    tokens = _tok("Kernel panic - not syncing: fatal")
    assert tokens[0].confidence == 1.0

def test_confidence_unknown_type():
    tokens = _tok("completely unrecognized log line xyz")
    assert tokens[0].confidence == 0.1


# ── Architecture detection — EC-05 ───────────────────────────────────────────

def test_arch_x86_detected_from_rip():
    tokens = _tok("Linux version 6.8.0\nRIP: 0010:crash+0x7c\nRSP: 0018:fff")
    assert all(t.arch == "x86_64" for t in tokens)

def test_arch_arm64_detected_from_pc():
    tokens = _tok("Linux version 6.8.0\npc : crash+0x48\nESR_EL1: 0x96000006")
    assert all(t.arch == "arm64" for t in tokens)

def test_arch_unknown_when_no_signal():
    tokens = _tok("Kernel panic - not syncing\nsome other line")
    assert all(t.arch == "unknown" for t in tokens)

def test_arch_hint_overrides_detection():
    tokens = _tok("RIP: 0010:crash+0x7c", arch_hint="arm64")
    assert tokens[0].arch == "arm64"

def test_arch_propagates_to_later_tokens():
    tokens = _tok("generic line\npc : crash+0x48\ngeneric line 2")
    assert tokens[2].arch == "arm64"


# ── Chip generation detection ─────────────────────────────────────────────────

def test_chip_gen_amd_cdna3():
    tokens = _tok("amdgpu: MI300 detected")
    assert tokens[0].chip_gen == "amd_cdna3"

def test_chip_gen_amd_cdna2():
    tokens = _tok("amdgpu: Aldebaran GPU reset")
    assert tokens[0].chip_gen == "amd_cdna2"

def test_chip_gen_intel_dg2():
    tokens = _tok("i915: DG2 GT2 512 EU initialized")
    assert tokens[0].chip_gen == "intel_dg2"

def test_chip_gen_qualcomm_sm8550():
    tokens = _tok("SM8550: adreno detected")
    assert tokens[0].chip_gen == "qcom_sm8550"

def test_chip_gen_nvidia_hopper():
    tokens = _tok("NVRM: GH100 GPU Board Initialization")
    assert tokens[0].chip_gen == "nvidia_hopper"

def test_chip_gen_unknown_fallback():
    tokens = _tok("kernel: [   0.000000] Booting Linux")
    assert all(t.chip_gen == "unknown" for t in tokens)

def test_chip_gen_hint_overrides():
    tokens = _tok("Aldebaran GPU", chip_gen_hint="amd_cdna3")
    assert tokens[0].chip_gen == "amd_cdna3"


# ── Kernel version ────────────────────────────────────────────────────────────

def test_kernel_ver_extracted():
    tokens = _tok("Linux version 6.8.0-45-generic (buildd@lcy02)")
    assert tokens[0].kernel_ver == "6.8.0-45-generic"

def test_kernel_ver_propagated():
    tokens = _tok("Linux version 6.8.0\nCall Trace:\nRIP: 0010:crash+0x4")
    assert tokens[1].kernel_ver == "6.8.0"
    assert tokens[2].kernel_ver == "6.8.0"

def test_kernel_ver_none_if_absent():
    tokens = _tok("Kernel panic - not syncing\nRIP: 0010:crash")
    assert all(t.kernel_ver is None for t in tokens)


# ── Timestamp ─────────────────────────────────────────────────────────────────

def test_timestamp_dmesg():
    tokens = _tok("[12345.678901] Kernel panic - not syncing")
    assert tokens[0].timestamp == "12345.678901"

def test_timestamp_journald():
    tokens = _tok("2026-01-01T00:00:05+05:30 kernel: Kernel panic")
    assert tokens[0].timestamp is not None

def test_timestamp_none():
    tokens = _tok("Kernel panic - not syncing")
    assert tokens[0].timestamp is None


# ── Duplicate detection — EC-04 ──────────────────────────────────────────────

def test_duplicate_flagged_in_window():
    line = "Kernel panic - not syncing"
    tokens = _tok(f"{line}\nother line\n{line}", dedup_window=50)
    assert tokens[0].is_duplicate is False
    assert tokens[2].is_duplicate is True

def test_duplicate_not_flagged_outside_window():
    line = "Kernel panic - not syncing"
    filler = "\n".join(["filler"] * 60)
    tokens = _tok(f"{line}\n{filler}\n{line}", dedup_window=50)
    assert tokens[-1].is_duplicate is False

def test_no_duplicates_in_clean_log():
    tokens = _tok("line one\nline two\nline three")
    assert all(not t.is_duplicate for t in tokens)


# ── Line numbering ────────────────────────────────────────────────────────────

def test_line_numbers_1_based():
    tokens = _tok("a\nb\nc")
    assert [t.line_no for t in tokens] == [1, 2, 3]


# ── Streaming safety — EC-06 ──────────────────────────────────────────────────

def test_tokenize_is_generator():
    assert isinstance(tokenize(iter(["x"])), types.GeneratorType)

def test_large_log_does_not_buffer(tmp_path):
    import resource

    def big_log():
        for i in range(500_000):
            yield f"[{i}.000000] kernel: log line {i}"

    before_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in tokenize(big_log()):
        pass
    after_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    delta_mb = (after_kb - before_kb) / 1024
    assert delta_mb < 40, f"Tokenizer buffered too much: {delta_mb:.1f} MB"


# ── Fixture integration ───────────────────────────────────────────────────────

def test_fixture_amd_produces_tokens():
    from soctriage.core.input_handler import open_log
    it, _ = open_log(FIXTURES / "amd/gpu_hang_gfx.log")
    tokens = list(tokenize(it))
    assert len(tokens) > 0

def test_fixture_intel_chip_gen_detected():
    from soctriage.core.input_handler import open_log
    it, _ = open_log(FIXTURES / "intel/guc_hang.log")
    tokens = list(tokenize(it))
    assert len(tokens) > 0
    assert any(t.chip_gen.startswith("intel") for t in tokens)

def test_fixture_qualcomm_arch_detected():
    from soctriage.core.input_handler import open_log
    it, _ = open_log(FIXTURES / "qualcomm/arm64_qcom_panic.log")
    tokens = list(tokenize(it))
    assert any(t.arch == "arm64" for t in tokens)


# ── Line normalization ────────────────────────────────────────────────────────

def test_ansi_escape_stripped_before_matching():
    """ANSI color codes must not prevent pattern matching."""
    # Serial console/journald output: "Kernel\x1b[1m panic\x1b[0m - not syncing"
    tokens = list(tokenize(iter(["Kernel\x1b[1m panic\x1b[0m - not syncing"])))
    assert tokens[0].token_type == "panic"

def test_carriage_return_stripped():
    """Windows CRLF endings: \\r must be stripped before matching."""
    tokens = list(tokenize(iter(["Kernel panic - not syncing\r"])))
    assert tokens[0].token_type == "panic"

def test_null_byte_stripped():
    """Null bytes in log lines must not corrupt pattern matching."""
    tokens = list(tokenize(iter(["Kernel\x00 panic - not syncing"])))
    assert tokens[0].token_type == "panic"

def test_raw_field_preserves_original_line():
    """LogToken.raw must store the original unmodified line."""
    original = "Kernel\x1b[1m panic\x1b[0m\r"
    tokens = list(tokenize(iter([original])))
    assert tokens[0].raw == original


# ── Timestamp formats ─────────────────────────────────────────────────────────

def test_timestamp_journal_fractional_seconds():
    """ISO 8601 with fractional seconds must parse correctly."""
    tokens = list(tokenize(iter(["2026-01-15T10:30:45.123456+00:00 kernel: panic"])))
    assert tokens[0].timestamp == "2026-01-15T10:30:45.123456+00:00"

def test_timestamp_journal_utc_z():
    """ISO 8601 with Z suffix must parse correctly."""
    tokens = list(tokenize(iter(["2026-01-15T10:30:45Z kernel: panic"])))
    assert tokens[0].timestamp == "2026-01-15T10:30:45Z"

def test_timestamp_syslog_format():
    """Traditional syslog 'Mon DD HH:MM:SS' timestamps must be extracted."""
    tokens = list(tokenize(iter(["Jan 15 10:30:45 hostname kernel: panic"])))
    assert tokens[0].timestamp == "Jan 15 10:30:45"


# ── Dedup correctness ─────────────────────────────────────────────────────────

def test_dedup_repeated_line_beyond_window_stays_detected():
    """A line repeated >window times: after oldest evicts, later copies still in
    window must still be detected as duplicates (Counter vs naive set bug)."""
    n = 10
    spam = "irq 42: nobody cared"
    tokens = list(tokenize(iter([spam] * (n + 1)), dedup_window=n))
    assert tokens[0].is_duplicate is False
    assert all(t.is_duplicate is True for t in tokens[1:])

def test_dedup_window_zero_no_crash():
    """dedup_window=0 must not crash and must mark nothing as duplicate."""
    tokens = list(tokenize(iter(["same line", "same line"]), dedup_window=0))
    assert all(not t.is_duplicate for t in tokens)
