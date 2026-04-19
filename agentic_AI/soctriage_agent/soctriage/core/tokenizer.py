"""
tokenizer.py — Phase 2 v2.0.0
YAML-driven tokenizer engine. Consumes a line iterator and yields one typed LogToken
per line. All token type knowledge lives in YAML files loaded through TokenRuleRegistry.
The engine is frozen after Phase 2.
"""

from __future__ import annotations

import collections
import itertools
import re
from dataclasses import dataclass
from typing import Iterator

from soctriage.core.token_rule import TokenContext, TokenRule, TokenRuleRegistry

__all__ = ["LogToken", "tokenize"]


# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class LogToken:
    line_no:      int
    raw:          str        # original line (before normalization)
    token_type:   str        # first-match by priority from YAML rules
    arch:         str        # "x86_64" | "arm64" | "unknown" — forward-propagated
    chip_gen:     str        # "amd_cdna3" | "unknown" — forward-propagated
    kernel_ver:   str | None  # extracted once, propagated forward
    timestamp:    str | None  # raw string, no datetime parsing
    is_duplicate: bool        # exact-match within dedup_window
    confidence:   float       # 1.0 for matched type, 0.1 for "unknown"


# ── Line normalization ────────────────────────────────────────────────────────

# Strip ANSI/VT escape sequences (colors, cursor movement, etc.) that appear
# in serial console captures and colored journald output.  Leaving them in
# breaks pattern matching — e.g. "kernel\x1b[1m panic\x1b[0m" won't hit
# a "kernel panic" rule.
_RE_ANSI_ESCAPE = re.compile(
    r'\x1b'           # ESC
    r'(?:'
    r'\[[0-9;]*[A-Za-z]'   # CSI sequences: ESC [ ... letter
    r'|[()][0-9A-Za-z]'    # charset designations: ESC ( X
    r'|[A-Z]'              # two-char sequences: ESC A ... ESC Z
    r')'
)

# Control characters to strip after ANSI removal.
# Excludes \t (0x09, tab — legitimate in some log formats).
# Strips \x00–\x08, \x0b–\x0c, \x0e–\x1f, \x7f.
_RE_CTRL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _normalize(line: str) -> str:
    """
    Return a clean version of a log line suitable for regex matching.

    Strips:
      - Trailing \\r (Windows/serial CRLF line endings)
      - ANSI/VT escape sequences
      - Non-printable control characters (except \\t)

    The original line is preserved in LogToken.raw for display.
    """
    line = line.rstrip('\r')
    line = _RE_ANSI_ESCAPE.sub('', line)
    line = _RE_CTRL_CHARS.sub('', line)
    return line


# ── Public entry point ────────────────────────────────────────────────────────


def tokenize(
    lines: Iterator[str],
    *,
    arch_hint:     str | None               = None,
    chip_gen_hint: str | None               = None,
    dedup_window:  int                      = 50,
    rule_registry: TokenRuleRegistry | None = None,
) -> Iterator[LogToken]:
    """
    Consume a line iterator and yield one LogToken per line.

    Generator — never buffers the full log (streaming-safe for >100MB files).

    Arch and chip_gen are detected via a 200-line lookahead buffer so tokens
    appearing before the detection signal still receive the correct values.
    Kernel version is extracted once and propagated to all subsequent tokens.
    Each line is normalized (ANSI escapes, control chars, \\r stripped) before
    pattern matching; the raw original is stored in LogToken.raw.
    """
    _DETECT_WINDOW = 200

    registry = rule_registry or _default_registry()

    # ── Pre-scan buffer: detect arch + chip_gen before yielding any tokens ────
    source = iter(lines)
    buf: list[str] = []
    for line in source:
        buf.append(line)
        if len(buf) >= _DETECT_WINDOW:
            break

    initial_arch:     str | None = arch_hint
    initial_chip_gen: str | None = chip_gen_hint

    if initial_arch is None or initial_chip_gen is None:
        for pre_line in buf:
            norm = _normalize(pre_line)
            if initial_arch is None:
                detected = _detect_arch(norm)
                if detected != "unknown":
                    initial_arch = detected
            if initial_chip_gen is None:
                detected_cg = _detect_chip_gen(norm)
                if detected_cg != "unknown":
                    initial_chip_gen = detected_cg
            if initial_arch is not None and initial_chip_gen is not None:
                break

    # ── Stream all lines (buffer + remainder) ─────────────────────────────────
    current_arch:     str        = initial_arch     if initial_arch     is not None else "unknown"
    current_chip_gen: str        = initial_chip_gen if initial_chip_gen is not None else "unknown"
    current_kver:     str | None = None

    # Dedup: deque tracks insertion order for eviction; Counter provides O(1)
    # lookup and correctly handles lines that appear multiple times in the window
    # (a set would incorrectly evict a line still present at a later position).
    dedup_deque:  collections.deque[str]      = collections.deque(maxlen=dedup_window)
    dedup_counts: collections.Counter[str]    = collections.Counter()

    recent_toks:  collections.deque[LogToken] = collections.deque(maxlen=50)
    recent_types: collections.deque[str]      = collections.deque(maxlen=50)

    all_lines: Iterator[str] = itertools.chain(iter(buf), source)

    for line_no, raw_line in enumerate(all_lines, start=1):
        line = _normalize(raw_line)

        # Extend arch/chip_gen detection beyond the pre-scan buffer
        if arch_hint is None and current_arch == "unknown":
            d = _detect_arch(line)
            if d != "unknown":
                current_arch = d

        if chip_gen_hint is None and current_chip_gen == "unknown":
            cg = _detect_chip_gen(line)
            if cg != "unknown":
                current_chip_gen = cg

        # Kernel version: extract once, propagate forward
        if current_kver is None:
            kv = _extract_kernel_ver(line)
            if kv is not None:
                current_kver = kv

        # Timestamp
        ts = _extract_timestamp(line)

        # Duplicate detection: O(1) Counter lookup.
        # Guard: dedup_window=0 means no dedup — maxlen=0 deque drops everything
        # and the condition len==maxlen (0==0) would fire on an empty deque.
        if dedup_deque.maxlen:
            is_dup = dedup_counts[line] > 0
            if len(dedup_deque) == dedup_deque.maxlen:
                evicted = dedup_deque[0]      # oldest entry (auto-evicted next)
                dedup_counts[evicted] -= 1
                if dedup_counts[evicted] == 0:
                    del dedup_counts[evicted]
            dedup_deque.append(line)
            dedup_counts[line] += 1
        else:
            is_dup = False

        # Derive provider string from chip_gen prefix (used by provider-specific rules)
        provider = _chip_gen_to_provider(current_chip_gen)

        # Classify via registry (match against normalized line).
        # Pass deques directly — avoids copying 50-element deques on every line.
        ctx = TokenContext(
            line_no       = line_no,
            arch          = current_arch,
            chip_gen      = current_chip_gen,
            provider      = provider,
            recent_tokens = recent_toks,
            recent_types  = recent_types,
        )
        token_type = registry.match(line, ctx)

        token = LogToken(
            line_no      = line_no,
            raw          = raw_line,
            token_type   = token_type,
            arch         = current_arch,
            chip_gen     = current_chip_gen,
            kernel_ver   = current_kver,
            timestamp    = ts,
            is_duplicate = is_dup,
            confidence   = 1.0 if token_type != "unknown" else 0.1,
        )
        recent_toks.append(token)
        recent_types.append(token_type)
        yield token


# ── Registry factory (singleton) ──────────────────────────────────────────────

# Module-level singleton: YAML files are read from disk and regexes compiled
# exactly once per process.  Tests that need isolation pass their own registry
# via the rule_registry parameter.
_registry_singleton: TokenRuleRegistry | None = None


def _default_registry() -> TokenRuleRegistry:
    """Return the shared default registry, loading it on first call."""
    global _registry_singleton
    if _registry_singleton is None:
        r = TokenRuleRegistry()
        r.load_defaults()
        _registry_singleton = r
    return _registry_singleton


# ── Provider derivation ───────────────────────────────────────────────────────

# Maps the leading segment of chip_gen to the provider name used in YAML rules.
_CHIP_GEN_PREFIX_TO_PROVIDER: dict[str, str] = {
    "intel":   "intel",
    "amd":     "amd",
    "qcom":    "qcom",
    "nvidia":  "nvidia",
}


def _chip_gen_to_provider(chip_gen: str) -> str:
    """Return the provider name for a chip_gen string, or "unknown"."""
    prefix = chip_gen.split("_")[0]
    return _CHIP_GEN_PREFIX_TO_PROVIDER.get(prefix, "unknown")


# ── Arch detection ────────────────────────────────────────────────────────────

_RE_ARCH_ARM64 = re.compile(r'^pc\s*:|^lr\s*:|^sp\s*:|^x\d{1,2}:\s|ESR_EL1|FAR_EL1')
_RE_ARCH_X86   = re.compile(r'^RIP:|^R[SABCD]X:|^RSP:|^CR[23]:')


def _detect_arch(line: str) -> str:
    """Return "arm64", "x86_64", or "unknown"."""
    if _RE_ARCH_ARM64.search(line):
        return "arm64"
    if _RE_ARCH_X86.search(line):
        return "x86_64"
    return "unknown"


# ── Chip generation detection ─────────────────────────────────────────────────

# Each entry: (list_of_keywords, chip_gen_string).
# Keywords are matched with word boundaries to prevent "MI100" matching "MI1000".
# Most-specific entries come first within each vendor group.
_CHIP_GEN_RULES: list[tuple[list[re.Pattern[str]], str]] = [
    # AMD — most specific first
    ([re.compile(r'\bMI300\b'),         re.compile(r'\bAqua Vanjaram\b')],  "amd_cdna3"),
    ([re.compile(r'\bAldebaran\b'),     re.compile(r'\bMI200\b')],          "amd_cdna2"),
    ([re.compile(r'\bArcturus\b'),      re.compile(r'\bMI100\b')],          "amd_cdna1"),
    ([re.compile(r'\bNavi31\b'),        re.compile(r'\bRX 7900\b')],        "amd_rdna3"),
    ([re.compile(r'\bNavi21\b'),        re.compile(r'\bRX 6900\b')],        "amd_rdna2"),
    ([re.compile(r'\bNavi10\b'),        re.compile(r'\bRX 5700\b')],        "amd_rdna1"),
    ([re.compile(r'\bVega10\b'),        re.compile(r'\bVega20\b')],         "amd_pre_navi"),
    ([re.compile(r'\bamdgpu\b')],                                            "amd_unknown"),
    # Intel — most specific first
    ([re.compile(r'\bDG2\b'),           re.compile(r'\bAlchemist\b'),
      re.compile(r'\bFlex Series\b'),   re.compile(r'\bArc A\b')],          "intel_dg2"),
    ([re.compile(r'\bXe HP\b'),         re.compile(r'\bPonte Vecchio\b'),
      re.compile(r'\bPVC\b')],                                               "intel_xe_hpc"),
    ([re.compile(r'\bXe2\b'),           re.compile(r'\bBattlemage\b'),
      re.compile(r'\bLunar Lake\b')],                                        "intel_xe2"),
    ([re.compile(r'\bMeteor Lake\b'),   re.compile(r'\bMTL\b')],            "intel_mtl"),
    ([re.compile(r'\bTiger Lake\b'),    re.compile(r'\bTGL\b'),
      re.compile(r'\bGEN12\b')],                                             "intel_gen12"),
    ([re.compile(r'\bIce Lake\b'),      re.compile(r'\bICL\b'),
      re.compile(r'\bGEN11\b')],                                             "intel_gen11"),
    ([re.compile(r'\bi915\b')],                                              "intel_unknown"),
    # Qualcomm
    ([re.compile(r'\bSM8550\b'),        re.compile(r'\bSnapdragon 8 Gen 2\b')], "qcom_sm8550"),
    ([re.compile(r'\bSM8450\b'),        re.compile(r'\bSnapdragon 8 Gen 1\b')], "qcom_sm8450"),
    ([re.compile(r'\bSM8350\b'),        re.compile(r'\bSnapdragon 888\b')],     "qcom_sm8350"),
    ([re.compile(r'\bSM8250\b'),        re.compile(r'\bSnapdragon 865\b')],     "qcom_sm8250"),
    ([re.compile(r'\bSDM845\b'),        re.compile(r'\bSnapdragon 845\b')],     "qcom_sdm845"),
    ([re.compile(r'\bSC8280XP\b'),      re.compile(r'\bSnapdragon 8cx Gen 3\b')], "qcom_sc8280xp"),
    ([re.compile(r'\bmsm\b'),           re.compile(r'\bqcom\b')],               "qcom_unknown"),
    # NVIDIA
    ([re.compile(r'\bGB100\b'),         re.compile(r'\bGB200\b'),
      re.compile(r'\bBlackwell\b')],                                         "nvidia_blackwell"),
    ([re.compile(r'\bGH100\b'),         re.compile(r'\bH100\b'),
      re.compile(r'\bHopper\b')],                                            "nvidia_hopper"),
    ([re.compile(r'\bGA100\b'),         re.compile(r'\bA100\b'),
      re.compile(r'\bAmpere\b')],                                            "nvidia_ampere"),
    ([re.compile(r'\bTU102\b'),         re.compile(r'\bRTX 20\b'),
      re.compile(r'\bTuring\b')],                                            "nvidia_turing"),
    ([re.compile(r'\bnvidia\b'),        re.compile(r'\bnouveau\b')],         "nvidia_unknown"),
]


def _detect_chip_gen(line: str) -> str:
    """Return chip generation string or "unknown"."""
    for patterns, chip_gen in _CHIP_GEN_RULES:
        if any(p.search(line) for p in patterns):
            return chip_gen
    return "unknown"


# ── Kernel version extraction ─────────────────────────────────────────────────

_RE_KERNEL_VER = re.compile(r'Linux version (\S+)')


def _extract_kernel_ver(line: str) -> str | None:
    m = _RE_KERNEL_VER.search(line)
    return m.group(1) if m else None


# ── Timestamp extraction ──────────────────────────────────────────────────────

_RE_TS_DMESG = re.compile(r'^\[\s*(\d+\.\d+)\]')

# ISO 8601 / journald: 2024-01-15T10:30:45[.fractional][Z|+HH:MM|-HH:MM]
# Fractional seconds are optional; timezone designator is optional.
_RE_TS_JOURNAL = re.compile(
    r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
    r'(?:\.\d+)?'                    # optional fractional seconds
    r'(?:Z|[+\-]\d{2}:\d{2})?'      # optional timezone offset or Z
    r')'
)

# Syslog traditional: "Jan 15 10:30:45" or "Jan  5 10:30:45" (single-digit day)
_RE_TS_SYSLOG = re.compile(
    r'^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})'
)


def _extract_timestamp(line: str) -> str | None:
    m = _RE_TS_DMESG.match(line)
    if m:
        return m.group(1)
    m = _RE_TS_JOURNAL.match(line)
    if m:
        return m.group(1)
    m = _RE_TS_SYSLOG.match(line)
    if m:
        return m.group(1)
    return None
