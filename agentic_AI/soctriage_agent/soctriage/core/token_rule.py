"""
token_rule.py — Phase 2 v2.0.0 full implementation
YAML-driven token rule engine: TokenRule, TokenContext, CompiledRule, TokenRuleRegistry.
The engine is frozen after Phase 2; all new token types are added via YAML files only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

__all__ = ["TokenRule", "TokenContext", "CompiledRule", "TokenRuleRegistry"]

# ── Allowlists ────────────────────────────────────────────────────────────────

# Valid match modes — allowlist checked at load time so misconfigured YAML fails loudly.
_VALID_MATCH_MODES: frozenset[str] = frozenset({"any", "all", "context", "negative"})

# Valid arch values — allowlist prevents arbitrary strings from silently passing filters.
_VALID_ARCH_VALUES: frozenset[str] = frozenset({
    "any", "x86_64", "arm64", "arm", "riscv64", "mips", "mips64", "powerpc", "s390x",
})

# token_type must be a lowercase identifier: letters, digits, underscores.
_RE_TOKEN_TYPE = re.compile(r'^[a-z][a-z0-9_]*$')

# Type alias: patterns may be a literal string (matched verbatim) or a dict
# with a single "regex" key (matched as a compiled regex).
PatternItem = str | dict[str, str]


# ── Data definitions ──────────────────────────────────────────────────────────


@dataclass
class TokenContext:
    """Runtime context passed to each rule match call."""
    line_no:       int
    arch:          str              # "x86_64" | "arm64" | "unknown"
    chip_gen:      str              # "amd_cdna3" | "unknown" etc.
    provider:      str              # "intel" | "amd" | "qcom" | "nvidia" | "unknown"
    recent_tokens: Sequence[Any]   # previous N LogTokens (may be a deque)
    recent_types:  Sequence[str]   # token_type values from preceding N tokens (may be a deque)


@dataclass
class TokenRule:
    """Single rule definition — loaded from YAML or registered programmatically."""
    token_type:       str
    priority:         int                  # 1–200, higher = checked first
    match_mode:       str                  # any | all | context | negative
    patterns:         list[PatternItem]
    exclude_patterns: list[PatternItem]    = field(default_factory=list)
    arch:             str                  = "any"
    providers:        list[str]            = field(default_factory=lambda: ["any"])
    context_before:   dict[str, Any] | None = None
    context_after:    dict[str, Any] | None = None  # reserved for Phase 2e
    capture_group:    int | None           = None   # reserved for Phase 2e
    store_as:         str | None           = None   # reserved for Phase 2e
    notes:            str                  = ""


# ── CompiledRule ──────────────────────────────────────────────────────────────


def _compile_pattern(p: PatternItem) -> re.Pattern[str]:
    """Compile one pattern item — dict {"regex": "..."} or literal string."""
    if isinstance(p, dict):
        return re.compile(p["regex"])
    return re.compile(re.escape(p))


class CompiledRule:
    """Pre-compiled regex form of TokenRule — compiled once at load time."""

    def __init__(self, rule: TokenRule) -> None:
        self.rule = rule
        # re.error propagates up — callers (load_yaml) add file/rule context
        self._compiled: list[re.Pattern[str]] = [
            _compile_pattern(p) for p in rule.patterns
        ]
        self._excluded: list[re.Pattern[str]] = [
            _compile_pattern(p) for p in rule.exclude_patterns
        ]
        # Pre-compute whether this rule targets any provider (fast-path)
        self._any_provider: bool = "any" in rule.providers

    def matches(self, line: str, ctx: TokenContext) -> bool:
        """Return True if this rule matches line in the given context."""
        # Arch filter: skip if rule is arch-specific and ctx arch is known and different.
        # "unknown" context arch never blocks — we can't be sure it doesn't match.
        if self.rule.arch != "any" and ctx.arch not in ("unknown", self.rule.arch):
            return False

        # Provider filter: skip if rule targets specific providers and ctx provider
        # is known and not in the list.  "unknown" context provider never blocks.
        if not self._any_provider and ctx.provider not in ("unknown", *self.rule.providers):
            return False

        # Exclude patterns bail-out — checked before include patterns
        if self._excluded and any(r.search(line) for r in self._excluded):
            return False

        mode = self.rule.match_mode

        if mode == "any":
            return any(r.search(line) for r in self._compiled)

        if mode == "all":
            return all(r.search(line) for r in self._compiled)

        if mode == "negative":
            # "negative" fires when the line CONTAINS the signal.
            # The token_type name describes a negative outcome; the match logic
            # is identical to "any".
            return any(r.search(line) for r in self._compiled)

        if mode == "context":
            if not any(r.search(line) for r in self._compiled):
                return False
            cb = self.rule.context_before
            if cb:
                window: int = cb.get("window", 10)
                required: list[str] = cb.get("must_contain_type", [])
                # Convert to list only here (deque doesn't support slice)
                recent = list(ctx.recent_types)[-window:]
                if not any(t in recent for t in required):
                    return False
            return True

        # Unreachable — match_mode is allowlist-validated at load time
        return False  # pragma: no cover


# ── TokenRuleRegistry ─────────────────────────────────────────────────────────


class TokenRuleRegistry:
    """
    Loads YAML rule files and provides first-match lookup by priority.

    Usage:
        registry = TokenRuleRegistry()
        registry.load_defaults()            # loads all *.yaml from token_rules/
        token_type = registry.match(line, ctx)
    """

    def __init__(self) -> None:
        self._rules: list[CompiledRule] = []
        self._sorted: bool = False

    def load_defaults(self) -> None:
        """Load all *.yaml files from the token_rules/ directory, then sort."""
        rules_dir = Path(__file__).parent / "token_rules"
        for yaml_file in sorted(rules_dir.glob("*.yaml")):
            self.load_yaml(yaml_file)
        self._sort()

    def load_yaml(self, path: Path) -> None:
        """
        Load a single YAML rule file and append its rules.

        Raises ValueError (with file + rule context) on:
          - YAML parse error
          - missing token_type
          - invalid token_type format
          - invalid match_mode
          - unknown arch value
          - regex compilation failure
        """
        import yaml  # deferred: yaml only required when loading rules

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Cannot read rule file {path}: {exc}") from exc

        try:
            # safe_load returns None for empty/comment-only files — treat as {}
            data: dict[str, Any] = yaml.safe_load(raw_text) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML parse error in {path}:\n{exc}") from exc

        for idx, rule_dict in enumerate(data.get("rules", [])):
            # ── Validate required field ──────────────────────────────────────
            if "token_type" not in rule_dict:
                raise ValueError(
                    f"{path} rule[{idx}]: missing required field 'token_type'"
                )

            token_type = str(rule_dict["token_type"]).strip()
            if not _RE_TOKEN_TYPE.match(token_type):
                raise ValueError(
                    f"{path} rule[{idx}]: token_type={token_type!r} must match "
                    f"[a-z][a-z0-9_]* (lowercase identifier)"
                )

            # ── Validate match_mode (allowlist) ──────────────────────────────
            match_mode = str(rule_dict.get("match_mode", "any")).strip()
            if match_mode not in _VALID_MATCH_MODES:
                raise ValueError(
                    f"{path} rule[{idx}] ({token_type!r}): "
                    f"invalid match_mode={match_mode!r}, "
                    f"must be one of {sorted(_VALID_MATCH_MODES)}"
                )

            # ── Validate arch (allowlist) ─────────────────────────────────────
            arch = str(rule_dict.get("arch", "any")).strip()
            if arch not in _VALID_ARCH_VALUES:
                raise ValueError(
                    f"{path} rule[{idx}] ({token_type!r}): "
                    f"unknown arch={arch!r}, "
                    f"must be one of {sorted(_VALID_ARCH_VALUES)}"
                )

            # ── Providers ────────────────────────────────────────────────────
            raw_providers = rule_dict.get("providers", ["any"])
            if isinstance(raw_providers, str):
                providers: list[str] = [raw_providers]
            else:
                providers = [str(p) for p in raw_providers]

            rule = TokenRule(
                token_type       = token_type,
                priority         = int(rule_dict.get("priority", 50)),
                match_mode       = match_mode,
                # `or []` guards against explicit YAML null (`patterns:` with no value)
                # which yaml.safe_load returns as None — list(None) would crash.
                patterns         = list(rule_dict.get("patterns") or []),
                exclude_patterns = list(rule_dict.get("exclude_patterns") or []),
                arch             = arch,
                providers        = providers,
                context_before   = rule_dict.get("context_before"),
                context_after    = rule_dict.get("context_after"),
                capture_group    = rule_dict.get("capture_group"),
                store_as         = rule_dict.get("store_as"),
                notes            = str(rule_dict.get("notes", "")),
            )

            # ── Compile regexes — wrap errors with file + rule context ────────
            try:
                compiled = CompiledRule(rule)
            except re.error as exc:
                raise ValueError(
                    f"{path} rule[{idx}] ({token_type!r}): "
                    f"invalid regex pattern: {exc}"
                ) from exc

            self._rules.append(compiled)

        self._sorted = False

    def register(self, rule: TokenRule) -> None:
        """Register a single TokenRule programmatically (e.g., from CLI or plugin)."""
        self._rules.append(CompiledRule(rule))
        self._sorted = False

    def _sort(self) -> None:
        """Sort rules descending by priority so highest-priority rules are checked first."""
        self._rules.sort(key=lambda r: r.rule.priority, reverse=True)
        self._sorted = True

    def match(self, line: str, ctx: TokenContext) -> str:
        """
        Return the token_type of the first matching rule (highest priority first).
        Always returns "unknown" as fallback — never raises.
        """
        if not self._sorted:
            self._sort()
        for rule in self._rules:
            if rule.matches(line, ctx):
                return rule.rule.token_type
        return "unknown"

    def rule_count(self) -> int:
        """Return the total number of loaded rules."""
        return len(self._rules)
