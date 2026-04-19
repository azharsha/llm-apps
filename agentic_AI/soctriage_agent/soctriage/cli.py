"""
cli.py — SoCTriage command-line interface.

Entry point: main()
Pipeline: open_log → tokenize → assemble → classify_all → analyse → render → output
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soctriage.core.token_rule import TokenRule

EXIT_SUCCESS    = 0
EXIT_NO_ANOMALY = 1
EXIT_PARSE_ERR  = 2
EXIT_INPUT_ERR  = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soctriage",
        description="SoCTriage — Agentic SoC Log Analysis System"
    )
    p.add_argument("--input",          type=str, metavar="PATH",
                   help="Input log file path, or - for stdin")
    p.add_argument("--output",         type=str, metavar="PATH",
                   help="Output report base path (extension added per --format)")
    p.add_argument("--format",         type=str, default="both",
                   choices=["json", "markdown", "both"],
                   help="Output format (default: both)")
    p.add_argument("--verbose",        action="store_true",
                   help="Enable debug output")
    p.add_argument("--llm",            action="store_true",
                   help="Enable LLM RCA narrative (Phase 6)")
    p.add_argument("--model",          type=str, default="claude-sonnet-4-6",
                   help="LLM model name (default: claude-sonnet-4-6)")
    p.add_argument("--ip-detail",      action="store_true",
                   help="Include per-IP register decode in output")
    p.add_argument("--asic-gen",       type=str, metavar="GEN",
                   help="Override ASIC/chip generation detection")
    p.add_argument("--soc-provider",   type=str, metavar="NAME",
                   help="Force specific SoC provider by name")
    p.add_argument("--list-providers", action="store_true",
                   help="List all registered providers and exit")
    p.add_argument("--token-rule", dest="extra_rules", action="append", default=[],
                   metavar="TYPE:PATTERN",
                   help="Inject an inline token rule. Format: token_type:pattern. Repeatable.")
    p.add_argument("--plugin", dest="plugin_files", action="append", default=[],
                   metavar="PATH",
                   help="Load a Python plugin file containing @register_rule rules. Repeatable.")
    return p


def _parse_inline_rule(rule_str: str) -> "TokenRule":  # noqa: F821
    """Parse 'TYPE:PATTERN' into a TokenRule. Exits with code 3 if format is invalid."""
    from soctriage.core.token_rule import TokenRule

    token_type, sep, pattern = rule_str.partition(":")
    if not sep:
        print(
            f"soctriage: --token-rule {rule_str!r}: invalid format, expected TYPE:PATTERN",
            file=sys.stderr,
        )
        sys.exit(EXIT_INPUT_ERR)
    return TokenRule(
        token_type = token_type.strip(),
        priority   = 190,
        match_mode = "any",
        patterns   = [pattern.strip()],
    )


def _build_registry():
    """Instantiate ProviderRegistry and auto-discover all providers."""
    from soctriage.core.provider_registry import ProviderRegistry
    registry = ProviderRegistry()
    providers_dir = Path(__file__).parent / "providers"
    registry.auto_discover(providers_dir)
    return registry


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # ── Logging ───────────────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # ── --list-providers ──────────────────────────────────────────────────────
    if args.list_providers:
        registry = _build_registry()
        names = registry.list_providers()
        if names:
            print("Registered providers:")
            for name in names:
                print(f"  {name}")
        else:
            print("No providers registered.")
        sys.exit(EXIT_SUCCESS)

    # ── Input required ────────────────────────────────────────────────────────
    if not args.input:
        parser.error("--input is required (use - for stdin)")

    # ── Phase 1: open log ─────────────────────────────────────────────────────
    from soctriage.core.input_handler import open_log, InputError

    try:
        lines, meta = open_log(args.input)
    except FileNotFoundError as exc:
        print(f"soctriage: error: {exc}", file=sys.stderr)
        sys.exit(EXIT_INPUT_ERR)
    except InputError as exc:
        print(f"soctriage: input error {exc.code}: {exc.message}", file=sys.stderr)
        sys.exit(EXIT_INPUT_ERR)

    if args.verbose:
        print(
            f"[input] source={meta.source_path}  "
            f"size={meta.size_bytes}B  "
            f"compression={meta.compression or 'none'}  "
            f"container={meta.container_hint or 'no'}",
            file=sys.stderr,
        )

    # ── Buffer head lines for provider detection ──────────────────────────────
    # Provider detection needs a string, but open_log returns a generator.
    # Buffer the first HEAD_LINES lines, join for detection, then chain back.
    HEAD_LINES = 500
    head_buf: list[str] = []
    line_iter = iter(lines)
    for _ in range(HEAD_LINES):
        try:
            head_buf.append(next(line_iter))
        except StopIteration:
            break

    head_text = "\n".join(head_buf)

    # ── Provider selection ────────────────────────────────────────────────────
    registry = _build_registry()

    if args.soc_provider:
        # Force a specific provider by name (case-insensitive substring match)
        wanted = args.soc_provider.lower()
        matched = next(
            (p for p in registry._providers if wanted in p.name().lower()),
            None,
        )
        if matched is None:
            print(
                f"soctriage: unknown provider {args.soc_provider!r}. "
                f"Available: {registry.list_providers()}",
                file=sys.stderr,
            )
            sys.exit(EXIT_PARSE_ERR)
        provider = matched
    else:
        provider = registry.detect_provider(head_text)

    if args.verbose:
        print(f"[provider] selected: {provider.name()}", file=sys.stderr)

    # ── Phase 2: tokenize (with plugin rules + inline rules) ─────────────────
    from soctriage.core.token_rule import TokenRuleRegistry
    from soctriage.core.plugin import PluginLoader
    from soctriage.core.tokenizer import tokenize

    rule_registry = TokenRuleRegistry()
    rule_registry.load_defaults()

    for pf in args.plugin_files:
        PluginLoader.load_file(Path(pf), rule_registry)

    for rule_str in args.extra_rules:
        rule_registry.register(_parse_inline_rule(rule_str))

    all_lines = itertools.chain(iter(head_buf), line_iter)
    tokens = tokenize(
        all_lines,
        chip_gen_hint=args.asic_gen,
        rule_registry=rule_registry,
    )

    # ── Phase 3: assemble + classify ─────────────────────────────────────────
    from soctriage.core.assembler import assemble
    from soctriage.core.classifier import classify_all

    events = list(classify_all(assemble(tokens, provider=provider), provider=provider))

    if args.verbose:
        print(f"[assembler] {len(events)} events assembled", file=sys.stderr)

    if not events:
        print("soctriage: no anomaly events found in log.", file=sys.stderr)
        sys.exit(EXIT_NO_ANOMALY)

    # ── Phase 4: cascade analysis ─────────────────────────────────────────────
    from soctriage.core.cascade import analyse
    from soctriage.core.ascii_diagram import render as render_diagram

    result = analyse(events, provider=provider)
    result.ascii_diagram = render_diagram(result)

    if args.verbose:
        print(
            f"[cascade] root_cause_id={result.root_cause_id}  "
            f"edges={len(result.edges)}  "
            f"severity={result.severity}  "
            f"analysis_ns={result.analysis_ns}",
            file=sys.stderr,
        )

    # ── Output ────────────────────────────────────────────────────────────────
    from soctriage.core.reporter import render_json, render_markdown

    fmt = args.format

    if args.output:
        out_base = Path(args.output)
        if fmt in ("json", "both"):
            out_path = out_base.with_suffix(".json")
            out_path.write_text(render_json(result), encoding="utf-8")
            if args.verbose:
                print(f"[output] JSON written to {out_path}", file=sys.stderr)
        if fmt in ("markdown", "both"):
            out_path = out_base.with_suffix(".md")
            out_path.write_text(render_markdown(result), encoding="utf-8")
            if args.verbose:
                print(f"[output] Markdown written to {out_path}", file=sys.stderr)
    else:
        # No output path — write to stdout
        if fmt in ("json", "both"):
            print(render_json(result))
        if fmt in ("markdown", "both"):
            if fmt == "both":
                print("\n---\n")  # separator between JSON and Markdown on stdout
            print(render_markdown(result))

    sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    main()
