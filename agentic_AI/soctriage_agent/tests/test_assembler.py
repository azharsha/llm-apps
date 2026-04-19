"""
test_assembler.py — Phase 3 v3.0.0
39 tests for LogEvent dataclass and assemble() state machine.
Expected: 39 PASSED, 0 FAILED
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from soctriage.core.tokenizer import LogToken
from soctriage.core.assembler import LogEvent, assemble

FIXTURES = Path("tests/fixtures/phase3")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tok(
    line_no: int,
    token_type: str,
    raw: str = "test line",
    arch: str = "unknown",
    chip_gen: str = "unknown",
    kernel_ver: str | None = None,
    is_duplicate: bool = False,
) -> LogToken:
    return LogToken(
        line_no=line_no,
        raw=raw,
        token_type=token_type,
        arch=arch,
        chip_gen=chip_gen,
        kernel_ver=kernel_ver,
        timestamp=None,
        is_duplicate=is_duplicate,
        confidence=1.0,
    )


def _assemble(*toks: LogToken, **kw) -> list[LogEvent]:
    return list(assemble(iter(toks), **kw))


# ── LogEvent dataclass ────────────────────────────────────────────────────────


def test_logevent_has_all_required_fields():
    tok = _tok(1, "panic")
    events = _assemble(tok)
    e = events[0]
    assert hasattr(e, "event_id")
    assert hasattr(e, "event_type")
    assert hasattr(e, "severity")
    assert hasattr(e, "subsystem")
    assert hasattr(e, "ip_block")
    assert hasattr(e, "tokens")
    assert hasattr(e, "start_line")
    assert hasattr(e, "end_line")
    assert hasattr(e, "arch")
    assert hasattr(e, "chip_gen")
    assert hasattr(e, "kernel_ver")
    assert hasattr(e, "confidence")
    assert hasattr(e, "raw_text")
    assert hasattr(e, "has_call_trace")
    assert hasattr(e, "has_registers")
    assert hasattr(e, "provider_name")


def test_logevent_raw_text_is_joined_tokens():
    t1 = _tok(1, "panic", raw="Kernel panic")
    t2 = _tok(2, "call_trace_header", raw="Call Trace:")
    events = _assemble(t1, t2)
    assert events[0].raw_text == "Kernel panic\nCall Trace:"


def test_logevent_has_call_trace_flag():
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header")
    t3 = _tok(3, "call_trace_frame")
    events = _assemble(t1, t2, t3)
    assert events[0].has_call_trace is True


def test_logevent_has_registers_flag():
    t1 = _tok(1, "oops_header")
    t2 = _tok(2, "register_dump")
    events = _assemble(t1, t2)
    assert events[0].has_registers is True


# ── assemble() basic contract ─────────────────────────────────────────────────


def test_assemble_returns_generator():
    result = assemble(iter([]))
    assert isinstance(result, types.GeneratorType)


def test_assemble_empty_stream_yields_nothing():
    """EC-16: empty stream → zero events, no error."""
    events = _assemble()
    assert events == []


def test_assemble_single_panic_yields_one_event():
    events = _assemble(_tok(1, "panic"))
    assert len(events) == 1


def test_assemble_event_type_kernel_panic():
    events = _assemble(_tok(1, "panic"))
    assert events[0].event_type == "kernel_panic"


def test_assemble_event_severity_critical_for_panic():
    events = _assemble(_tok(1, "panic"))
    assert events[0].severity == "critical"


# ── Boundary token detection ──────────────────────────────────────────────────


def test_panic_opens_new_event():
    events = _assemble(_tok(1, "panic"))
    assert len(events) == 1
    assert events[0].event_type == "kernel_panic"


def test_gpu_event_opens_new_event():
    events = _assemble(_tok(1, "gpu_event"))
    assert len(events) == 1
    assert events[0].event_type == "gpu_hang"


def test_reset_event_opens_new_event():
    events = _assemble(_tok(1, "reset_event"))
    assert len(events) == 1
    assert events[0].event_type == "gpu_reset"


def test_oom_event_opens_new_event():
    events = _assemble(_tok(1, "oom_event"))
    assert len(events) == 1
    assert events[0].event_type == "oom_kill"


def test_smmu_fault_opens_new_event():
    events = _assemble(_tok(1, "smmu_fault"))
    assert len(events) == 1
    assert events[0].event_type == "smmu_fault"


def test_qcom_adsp_crash_opens_new_event():
    """Qualcomm PD crash must open a soc_crash event."""
    events = _assemble(_tok(1, "qcom_adsp_crash"))
    assert len(events) == 1
    assert events[0].event_type == "soc_crash"


# ── Continuation token behaviour ──────────────────────────────────────────────


def test_call_trace_continues_panic_event():
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header")
    t3 = _tok(3, "call_trace_frame")
    events = _assemble(t1, t2, t3)
    assert len(events) == 1
    assert len(events[0].tokens) == 3
    assert events[0].has_call_trace is True


def test_register_dump_continues_oops_event():
    t1 = _tok(1, "oops_header")
    t2 = _tok(2, "register_dump")
    events = _assemble(t1, t2)
    assert len(events) == 1
    assert len(events[0].tokens) == 2
    assert events[0].has_registers is True


def test_kasan_detail_continues_memory_event():
    """kasan_detail is CONTINUATION — extends memory_event."""
    t1 = _tok(1, "memory_event")
    t2 = _tok(2, "kasan_detail")
    events = _assemble(t1, t2)
    assert len(events) == 1
    assert len(events[0].tokens) == 2


def test_sync_fence_continues_gpu_event():
    t1 = _tok(1, "gpu_event")
    t2 = _tok(2, "sync_fence_event")
    events = _assemble(t1, t2)
    assert len(events) == 1
    assert len(events[0].tokens) == 2


def test_gfx_cp_event_continues_gpu_event():
    t1 = _tok(1, "gpu_event")
    t2 = _tok(2, "gfx_cp_event")
    events = _assemble(t1, t2)
    assert len(events) == 1
    assert len(events[0].tokens) == 2


# ── Multi-event assembly ───────────────────────────────────────────────────────


def test_two_panics_yield_two_events():
    """EC-14: back-to-back panics produce two separate kernel_panic events."""
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header")
    t3 = _tok(10, "panic")  # far enough to open new event
    events = _assemble(t1, t2, t3)
    assert len(events) == 2
    assert events[0].event_type == "kernel_panic"
    assert events[1].event_type == "kernel_panic"


def test_gpu_hang_then_oom_yields_two_events():
    """EC-15: gpu_hang followed by oom_kill produces two separate events."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "multi_gpu_oom.log")
    toks = list(tokenize(it))
    events = list(assemble(iter(toks)))
    event_types = [e.event_type for e in events]
    assert "gpu_hang" in event_types
    assert "oom_kill" in event_types
    gpu_idx = next(i for i, e in enumerate(events) if e.event_type == "gpu_hang")
    oom_idx  = next(i for i, e in enumerate(events) if e.event_type == "oom_kill")
    assert gpu_idx < oom_idx


def test_back_to_back_gpu_resets():
    t1 = _tok(1, "reset_event")
    t2 = _tok(2, "reset_event")
    events = _assemble(t1, t2)
    assert len(events) == 2
    assert all(e.event_type == "gpu_reset" for e in events)


def test_info_tokens_collected_between_events():
    """Info tokens after the last event are flushed as info_event at stream end."""
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_frame")
    # Info tokens far from boundary → close event, collected in IDLE, flushed at end
    t3 = _tok(20, "info", raw="[20.000000] Some info line")
    events = _assemble(t1, t2, t3)
    # panic event closed when info arrives with gap > 5
    # info token collected in IDLE, flushed at stream end
    info_events = [e for e in events if e.event_type == "info_event"]
    assert len(info_events) >= 1


def test_qcom_adsp_cdsp_crash_fixture_two_events():
    """Fixture with ADSP + CDSP crashes must produce exactly 2 soc_crash events."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "qcom_adsp_cdsp_crash.log")
    toks = list(tokenize(it))
    events = list(assemble(iter(toks)))
    soc_events = [e for e in events if e.event_type == "soc_crash"]
    assert len(soc_events) == 2


def test_amd_cdna3_hang_fixture():
    """AMD MI300 fixture must yield a gpu_hang with amd_cdna3 chip_gen."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "amd_cdna3_hang.log")
    toks = list(tokenize(it))
    events = list(assemble(iter(toks)))
    gpu_events = [e for e in events if e.event_type == "gpu_hang"]
    assert len(gpu_events) >= 1
    e = gpu_events[0]
    assert e.chip_gen == "amd_cdna3"
    assert e.has_call_trace is True
    assert e.has_registers is True


# ── Duplicate handling ─────────────────────────────────────────────────────────


def test_duplicate_tokens_skipped_by_default():
    """EC-17: duplicate tokens are silently dropped when skip_duplicates=True."""
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header", is_duplicate=True)
    events = _assemble(t1, t2, skip_duplicates=True)
    assert len(events) == 1
    assert len(events[0].tokens) == 1  # only t1; t2 dropped


def test_skip_duplicates_false_includes_duplicates():
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header", is_duplicate=True)
    events = _assemble(t1, t2, skip_duplicates=False)
    assert len(events) == 1
    assert len(events[0].tokens) == 2


def test_duplicate_boundary_not_counted():
    """A duplicate BOUNDARY token is dropped and does not open a new event."""
    t1 = _tok(1, "panic")
    t2 = _tok(2, "panic", is_duplicate=True)  # duplicate: dropped
    events = _assemble(t1, t2, skip_duplicates=True)
    assert len(events) == 1  # t2 was dropped, no second event


# ── Edge cases ─────────────────────────────────────────────────────────────────


def test_ec09_truncated_log_event_closed():
    """EC-09: truncated log (stream ends mid-call-trace) → event is closed and emitted."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "truncated_call_trace.log")
    toks = list(tokenize(it))
    events = list(assemble(iter(toks)))
    assert len(events) >= 1
    assert events[0].event_type == "kernel_panic"
    assert events[0].has_call_trace is True


def test_ec18_custom_yaml_token_produces_unknown_event():
    """EC-18: token_type not in any known set → unknown_event, no crash."""
    t = _tok(1, "my_vendor_custom_token", raw="vendor subsystem fault code=0xDEAD")
    events = _assemble(t)
    assert len(events) == 1
    assert events[0].event_type == "unknown_event"
    assert events[0].severity == "info"


def test_ec19_max_event_lines_enforced():
    """EC-19: when token count reaches max_event_lines, event is force-closed."""
    # Build a stream: one panic followed by 5 continuation tokens
    toks = [_tok(1, "panic")]
    for i in range(2, 7):
        toks.append(_tok(i, "call_trace_frame"))
    events = list(assemble(iter(toks), max_event_lines=3))
    # First 3 tokens → force-closed event; remaining tokens → more events
    assert len(events) >= 2
    assert events[0].event_type == "kernel_panic"
    assert len(events[0].tokens) == 3


def test_ec20_interleaved_cpu_panics():
    """EC-20: each CPU panic is a separate event."""
    t1 = _tok(1, "panic", raw="CPU 0: Kernel panic")
    t2 = _tok(2, "panic", raw="CPU 1: Kernel panic")
    t3 = _tok(3, "panic", raw="CPU 2: Kernel panic")
    events = _assemble(t1, t2, t3)
    assert len(events) == 3
    assert all(e.event_type == "kernel_panic" for e in events)


def test_arm64_smmu_gpu_fixture_two_events():
    """SMMU fault followed by GPU hang must yield 2 events."""
    from soctriage.core.input_handler import open_log
    from soctriage.core.tokenizer import tokenize

    it, _ = open_log(FIXTURES / "arm64_smmu_gpu.log")
    toks = list(tokenize(it))
    events = list(assemble(iter(toks)))
    event_types = [e.event_type for e in events]
    assert "smmu_fault" in event_types
    assert "gpu_hang" in event_types


def test_unknown_event_not_none():
    """event_type is always a non-None string — never raises KeyError."""
    t = _tok(1, "completely_unknown_type_xyz")
    events = _assemble(t)
    assert events[0].event_type is not None
    assert isinstance(events[0].event_type, str)


# ── Line number tracking ───────────────────────────────────────────────────────


def test_event_start_line_is_boundary_token_line_no():
    t1 = _tok(42, "panic")
    t2 = _tok(43, "call_trace_header")
    events = _assemble(t1, t2)
    assert events[0].start_line == 42


def test_event_end_line_is_last_token_line_no():
    t1 = _tok(1, "panic")
    t2 = _tok(2, "call_trace_header")
    t3 = _tok(99, "call_trace_frame")
    events = _assemble(t1, t2, t3)
    assert events[0].end_line == 99


# ── arch + chip_gen propagation ────────────────────────────────────────────────


def test_event_arch_inherited_from_first_token():
    t = _tok(1, "panic", arch="arm64")
    events = _assemble(t)
    assert events[0].arch == "arm64"


def test_event_chip_gen_inherited_from_first_token():
    t = _tok(1, "gpu_event", chip_gen="amd_cdna3")
    events = _assemble(t)
    assert events[0].chip_gen == "amd_cdna3"
