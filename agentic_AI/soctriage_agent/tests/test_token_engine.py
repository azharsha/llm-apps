"""
test_token_engine.py — Phase 2 v2.0.0
20 tests covering TokenRuleRegistry mechanics.
Expected: 20 PASSED, 0 FAILED
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from soctriage.core.token_rule import (
    CompiledRule,
    TokenContext,
    TokenRule,
    TokenRuleRegistry,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

CORE_KERNEL_YAML = Path("soctriage/core/token_rules/core_kernel.yaml")

def _ctx(arch: str = "any", recent_types: list[str] | None = None) -> TokenContext:
    return TokenContext(
        line_no=1, arch=arch, chip_gen="unknown",
        recent_tokens=[], recent_types=recent_types or [],
    )

def _make_rule(token_type: str, priority: int = 50,
               match_mode: str = "any",
               patterns: list[str] | None = None,
               arch: str = "any",
               exclude_patterns: list[str] | None = None,
               context_before: dict | None = None) -> TokenRule:
    return TokenRule(
        token_type=token_type,
        priority=priority,
        match_mode=match_mode,
        patterns=patterns or ["MATCH_ME"],
        arch=arch,
        exclude_patterns=exclude_patterns or [],
        context_before=context_before,
    )


# ── YAML loading ──────────────────────────────────────────────────────────────

def test_load_yaml_adds_rules():
    r = TokenRuleRegistry()
    r.load_yaml(CORE_KERNEL_YAML)
    assert r.rule_count() > 0

def test_load_defaults_loads_core_kernel():
    r = TokenRuleRegistry()
    r.load_defaults()
    assert r.rule_count() >= 16

def test_load_empty_yaml_does_not_raise(tmp_path: Path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("version: 1\ncategory: test\nrules: []\n")
    r = TokenRuleRegistry()
    r.load_yaml(empty)
    assert r.rule_count() == 0

def test_load_comment_only_yaml_does_not_raise(tmp_path: Path):
    """safe_load returns None for comment-only YAML — must not crash."""
    f = tmp_path / "comments.yaml"
    f.write_text("# just a comment\n")
    r = TokenRuleRegistry()
    r.load_yaml(f)
    assert r.rule_count() == 0

def test_load_yaml_invalid_match_mode_raises(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - token_type: foo\n    priority: 50\n    match_mode: bogus\n"
        "    patterns: [MATCH]\n    arch: any\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    with pytest.raises(ValueError, match="invalid match_mode"):
        r.load_yaml(f)

def test_load_yaml_missing_token_type_raises(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - priority: 50\n    match_mode: any\n"
        "    patterns: [MATCH]\n    arch: any\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    with pytest.raises(ValueError, match="missing required field 'token_type'"):
        r.load_yaml(f)

def test_load_yaml_invalid_token_type_format_raises(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - token_type: 'Bad Type'\n    priority: 50\n    match_mode: any\n"
        "    patterns: [MATCH]\n    arch: any\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    with pytest.raises(ValueError, match="token_type"):
        r.load_yaml(f)

def test_load_yaml_invalid_arch_raises(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - token_type: foo\n    priority: 50\n    match_mode: any\n"
        "    patterns: [MATCH]\n    arch: sparc\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    with pytest.raises(ValueError, match="unknown arch"):
        r.load_yaml(f)

def test_load_yaml_bad_regex_raises_with_context(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - token_type: foo\n    priority: 50\n    match_mode: any\n"
        "    patterns:\n      - regex: '[unclosed'\n"
        "    arch: any\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    with pytest.raises(ValueError, match="invalid regex"):
        r.load_yaml(f)

def test_load_yaml_null_patterns_does_not_raise(tmp_path: Path):
    """Explicit YAML null value for patterns (e.g. 'patterns:') must not crash."""
    f = tmp_path / "null_patterns.yaml"
    f.write_text(
        "version: 1\nrules:\n"
        "  - token_type: foo\n    priority: 50\n    match_mode: any\n"
        "    patterns:\n"       # explicit null — yaml.safe_load returns None
        "    arch: any\n    providers: any\n"
    )
    r = TokenRuleRegistry()
    r.load_yaml(f)              # must not raise TypeError
    assert r.rule_count() == 1


# ── Priority ordering ─────────────────────────────────────────────────────────

def test_higher_priority_rule_wins():
    r = TokenRuleRegistry()
    r.register(_make_rule("low",  priority=10, patterns=["MATCH"]))
    r.register(_make_rule("high", priority=90, patterns=["MATCH"]))
    assert r.match("MATCH", _ctx()) == "high"

def test_priority_sort_after_register():
    r = TokenRuleRegistry()
    r.register(_make_rule("first",  priority=20, patterns=["FOO"]))
    r.register(_make_rule("second", priority=80, patterns=["FOO"]))
    r.register(_make_rule("third",  priority=50, patterns=["FOO"]))
    assert r.match("FOO", _ctx()) == "second"


# ── match_mode ────────────────────────────────────────────────────────────────

def test_match_mode_any():
    r = TokenRuleRegistry()
    r.register(_make_rule("t", match_mode="any", patterns=["ALPHA", "BETA"]))
    assert r.match("BETA line", _ctx()) == "t"

def test_match_mode_all_requires_both():
    r = TokenRuleRegistry()
    r.register(_make_rule("t", match_mode="all", patterns=["FOO", "BAR"]))
    assert r.match("FOO only", _ctx()) == "unknown"
    assert r.match("FOO and BAR", _ctx()) == "t"

def test_match_mode_context_requires_recent_type():
    r = TokenRuleRegistry()
    r.register(_make_rule(
        "frame", match_mode="context", patterns=["FRAME"],
        context_before={"window": 5, "must_contain_type": ["header"]},
    ))
    assert r.match("FRAME", _ctx(recent_types=[])) == "unknown"
    assert r.match("FRAME", _ctx(recent_types=["header"])) == "frame"

def test_match_mode_negative_returns_type():
    r = TokenRuleRegistry()
    r.register(_make_rule("neg", match_mode="negative", patterns=["SIGNAL"]))
    assert r.match("SIGNAL here", _ctx()) == "neg"


# ── Arch filtering ────────────────────────────────────────────────────────────

def test_arch_filter_skips_wrong_arch():
    r = TokenRuleRegistry()
    r.register(_make_rule("arm_rule", arch="arm64", patterns=["REG"]))
    assert r.match("REG", _ctx(arch="x86_64")) == "unknown"

def test_arch_filter_passes_matching_arch():
    r = TokenRuleRegistry()
    r.register(_make_rule("arm_rule", arch="arm64", patterns=["REG"]))
    assert r.match("REG", _ctx(arch="arm64")) == "arm_rule"

def test_arch_unknown_ctx_passes_arch_specific_rule():
    """arch="unknown" in context should not block arch-specific rules."""
    r = TokenRuleRegistry()
    r.register(_make_rule("arm_rule", arch="arm64", patterns=["REG"]))
    assert r.match("REG", _ctx(arch="unknown")) == "arm_rule"


# ── Exclude patterns ──────────────────────────────────────────────────────────

def test_exclude_patterns_prevents_match():
    r = TokenRuleRegistry()
    r.register(_make_rule("warn", patterns=["WARNING"], exclude_patterns=["circular locking"]))
    assert r.match("WARNING: possible circular locking dependency", _ctx()) == "unknown"

def test_exclude_patterns_allows_non_excluded():
    r = TokenRuleRegistry()
    r.register(_make_rule("warn", patterns=["WARNING"], exclude_patterns=["circular locking"]))
    assert r.match("WARNING: CPU: 3 at drivers/gpu/drm", _ctx()) == "warn"


# ── Unknown fallback ──────────────────────────────────────────────────────────

def test_unknown_fallback_when_no_rules():
    r = TokenRuleRegistry()
    assert r.match("anything", _ctx()) == "unknown"

def test_unknown_fallback_when_no_match():
    r = TokenRuleRegistry()
    r.register(_make_rule("t", patterns=["VERY_SPECIFIC_SIGNAL"]))
    assert r.match("some unrelated line", _ctx()) == "unknown"


# ── Rule count ────────────────────────────────────────────────────────────────

def test_rule_count_increments_on_register():
    r = TokenRuleRegistry()
    assert r.rule_count() == 0
    r.register(_make_rule("a"))
    assert r.rule_count() == 1
    r.register(_make_rule("b"))
    assert r.rule_count() == 2


# ── context_before window ─────────────────────────────────────────────────────

def test_context_window_uses_last_n_types():
    r = TokenRuleRegistry()
    r.register(_make_rule(
        "frame", match_mode="context", patterns=["FRAME"],
        context_before={"window": 3, "must_contain_type": ["header"]},
    ))
    # "header" is the first of 4 items; window=3 only looks at the last 3 → not found
    recent_outside = ["header", "other", "other", "other"]
    assert r.match("FRAME", _ctx(recent_types=recent_outside)) == "unknown"
    # "header" is within the last 3 items → found
    recent_inside = ["other", "header", "other"]
    assert r.match("FRAME", _ctx(recent_types=recent_inside)) == "frame"
