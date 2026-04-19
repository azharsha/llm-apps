"""
test_core_kernel_rules.py — Phase 2
18 tests validating every token type in core_kernel.yaml.
Expected: 18 PASSED, 0 FAILED
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/core_kernel.yaml")


def _reg() -> TokenRuleRegistry:
    r = TokenRuleRegistry()
    r.load_yaml(YAML)
    return r

def _ctx(arch: str = "any", recent_types: list[str] | None = None) -> TokenContext:
    return TokenContext(
        line_no=1, arch=arch, chip_gen="unknown",
        recent_tokens=[], recent_types=recent_types or [],
    )


# ── One test per token type ───────────────────────────────────────────────────

def test_panic_kernel_panic():
    r = _reg()
    assert r.match("Kernel panic - not syncing: fatal exception in interrupt", _ctx()) == "panic"

def test_panic_null_deref():
    r = _reg()
    assert r.match("BUG: kernel NULL pointer dereference, address: 0000000000000000", _ctx()) == "panic"

def test_oops_header_oops():
    r = _reg()
    assert r.match("Oops: 0002 [#1] SMP KASAN", _ctx()) == "oops_header"

def test_oops_header_unable_to_handle():
    r = _reg()
    assert r.match("Unable to handle kernel NULL pointer dereference at virtual address", _ctx()) == "oops_header"

def test_call_trace_header():
    r = _reg()
    assert r.match("Call Trace:", _ctx()) == "call_trace_header"

def test_call_trace_frame_with_context():
    r = _reg()
    ctx = _ctx(recent_types=["call_trace_header"])
    # Hex frame line
    assert r.match(" [<ffffffff81234567>] do_page_fault+0x4c/0x80", ctx) == "call_trace_frame"

def test_call_trace_frame_requires_context():
    r = _reg()
    ctx = _ctx(recent_types=[])
    assert r.match(" [<ffffffff81234567>] do_page_fault+0x4c/0x80", ctx) == "unknown"

def test_register_dump_x86():
    r = _reg()
    assert r.match("RIP: 0010:amdgpu_ttm_fault+0x7c/0x180", _ctx(arch="x86_64")) == "register_dump"

def test_register_dump_requires_x86_arch():
    r = _reg()
    # With arm64 arch, x86 register lines should not match register_dump
    result = r.match("RIP: 0010:amdgpu_ttm_fault+0x7c", _ctx(arch="arm64"))
    assert result != "register_dump"

def test_register_arm64():
    r = _reg()
    assert r.match("pc : adreno_crash+0x48/0x100", _ctx(arch="arm64")) == "register_arm64"

def test_register_arm64_requires_arm64_arch():
    r = _reg()
    result = r.match("pc : adreno_crash+0x48/0x100", _ctx(arch="x86_64"))
    assert result != "register_arm64"

def test_lockup_soft():
    r = _reg()
    assert r.match("watchdog: BUG: soft lockup - CPU#3 stuck for 22s!", _ctx()) == "lockup_soft"

def test_lockup_hard():
    r = _reg()
    assert r.match("NMI watchdog: Watchdog detected hard LOCKUP on cpu 1", _ctx()) == "lockup_hard"

def test_deadlock():
    r = _reg()
    assert r.match("WARNING: possible circular locking dependency detected", _ctx()) == "deadlock"

def test_rcu_stall():
    r = _reg()
    assert r.match("INFO: rcu_sched self-detected stall on CPU", _ctx()) == "rcu_stall"

def test_hung_task():
    r = _reg()
    assert r.match("INFO: task kworker/0:1:123 blocked for more than 120 seconds.", _ctx()) == "hung_task"

def test_stack_overflow():
    r = _reg()
    assert r.match("corrupted stack end detected inside scheduler", _ctx()) == "stack_overflow"

def test_warning():
    r = _reg()
    assert r.match("WARNING: CPU: 0 PID: 123 at kernel/sched/core.c:100", _ctx()) == "warning"

def test_warning_excludes_circular_locking():
    r = _reg()
    # Should be deadlock, not warning
    assert r.match("WARNING: possible circular locking dependency detected", _ctx()) == "deadlock"

def test_separator_cut_here():
    r = _reg()
    assert r.match("---[ cut here ]---", _ctx()) == "separator"

def test_info_linux_version():
    r = _reg()
    assert r.match("Linux version 6.8.0-45-generic (buildd@lcy02)", _ctx()) == "info"

def test_info_dmesg_bracket():
    r = _reg()
    assert r.match("[    0.000000] Booting Linux kernel", _ctx()) == "info"

def test_unknown_fallback():
    r = _reg()
    assert r.match("completely random line with no known signals abc123", _ctx()) == "unknown"


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_priority_lockup_beats_warning():
    """lockup_soft (118) > warning (80): 'BUG: soft lockup' should be lockup_soft."""
    r = _reg()
    assert r.match("BUG: soft lockup - CPU#3 stuck for 22s!", _ctx()) == "lockup_soft"

def test_priority_deadlock_beats_warning():
    """deadlock (117) > warning (80): circular locking lines should be deadlock."""
    r = _reg()
    result = r.match("WARNING: possible circular locking dependency detected", _ctx())
    assert result == "deadlock"
