"""
cli.py — SoCTriage command-line interface.

Entry point: main()
Pipeline: open_log → tokenize → assemble → classify_all → decode_hardware
          → analyse → run_agent → report → output
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from soctriage.core.agent import run_agent

if TYPE_CHECKING:
    from soctriage.core.token_rule import TokenRule
    from soctriage.core.agent_result import AgentResult

EXIT_SUCCESS    = 0
EXIT_NO_ANOMALY = 1
EXIT_PARSE_ERR  = 2
EXIT_INPUT_ERR  = 3

# Phase 7 semantic aliases
EXITOK       = EXIT_SUCCESS   # 0
EXITCRITICAL = 1
EXITERROR    = 2
EXITUSAGE    = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soctriage",
        description="SoCTriage — Agentic SoC Log Analysis System"
    )
    p.add_argument("--input",          type=str, metavar="PATH",
                   help="Input log file path, or - for stdin")
    p.add_argument("--output",         type=str, metavar="PATH",
                   help="Output report base path (extension added per --format)")
    p.add_argument("--format", dest="fmt", type=str, default=None,
                   choices=["json", "markdown", "html"],
                   help="Output format (default: json)")
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
    # Phase 7: positional LOG_FILE
    p.add_argument(
        "log_file", nargs="?", default=None, metavar="LOG_FILE",
        help="Kernel log file (.log .gz .bz2 .xz) or - for stdin",
    )
    # LLM control
    p.add_argument("--no-llm", action="store_true",
                   help="Skip LLM agent — Phase 4 cascade only")
    p.add_argument("--llm-backend", choices=["anthropic", "ollama"],
                   default="anthropic", dest="llm_backend")
    p.add_argument("--llm-model", default="claude-sonnet-4-5",
                   metavar="MODEL", dest="llm_model")
    p.add_argument("--ollama-host", default="http://localhost:11434",
                   metavar="URL", dest="ollama_host")
    p.add_argument("--timeout", type=int, default=60, metavar="SECS")
    p.add_argument("--include-raw", action="store_true", dest="include_raw",
                   help="Include raw event text in JSON output")
    p.add_argument("--version", action="store_true",
                   help="Show soctriage version and exit")
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


def _build_registry() -> "ProviderRegistry":  # type: ignore[name-defined]
    """Instantiate ProviderRegistry and auto-discover all providers."""
    from soctriage.core.provider_registry import ProviderRegistry
    registry = ProviderRegistry()
    providers_dir = Path(__file__).parent / "providers"
    registry.auto_discover(providers_dir)
    return registry


def _exit_code(agent_result: "AgentResult") -> int:
    if agent_result.cascade.severity == "critical":
        return EXITCRITICAL
    return EXITOK


def _vlog(verbose: bool, msg: str) -> None:
    if verbose:
        import time
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # ── Logging ───────────────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # ── --version ─────────────────────────────────────────────────────────────
    if args.version:
        try:
            import importlib.metadata
            ver = importlib.metadata.version("soctriage")
        except Exception:
            ver = "dev"
        print(f"soctriage {ver}")
        return EXITOK

    # ── --list-providers ──────────────────────────────────────────────────────
    if args.list_providers:
        from soctriage.providers import get_all_providers
        providers = get_all_providers()
        if providers:
            print("Registered providers:")
            for p in providers:
                print(f"  {p.name()}")
        else:
            print("No providers registered.")
        return EXITOK

    # ── Resolve log path (positional or --input fallback) ─────────────────────
    log_path = args.log_file or getattr(args, "input", None)
    if not log_path:
        parser.error("LOG_FILE or --input is required (use - for stdin)")
        return EXITUSAGE

    # ── Phase 1: open log ─────────────────────────────────────────────────────
    from soctriage.core.input_handler import open_log, InputError

    try:
        lines, meta = open_log(log_path)
    except FileNotFoundError as exc:
        print(f"soctriage: error: {exc}", file=sys.stderr)
        return EXITERROR
    except InputError as exc:
        print(f"soctriage: input error {exc.code}: {exc.message}", file=sys.stderr)
        return EXITERROR

    _vlog(args.verbose,
          f"[input] source={meta.source_path}  "
          f"size={meta.size_bytes}B  "
          f"compression={meta.compression or 'none'}  "
          f"container={meta.container_hint or 'no'}")

    # ── Buffer head lines for provider detection ──────────────────────────────
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
            return EXITUSAGE
        provider = matched
    else:
        provider = registry.detect_provider(head_text)

    _vlog(args.verbose, f"[provider] selected: {provider.name()}")

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

    _vlog(args.verbose, f"[assembler] {len(events)} events assembled")

    if not events:
        print("soctriage: no anomaly events found in log.", file=sys.stderr)
        return EXIT_NO_ANOMALY

    # ── Phase 3c: hardware decode ─────────────────────────────────────────────
    from soctriage.core.hardware_decode import decode_hardware

    events = decode_hardware(events, provider=provider)

    # ── Phase 4: cascade analysis ─────────────────────────────────────────────
    from soctriage.core.cascade import analyse
    from soctriage.core.ascii_diagram import render as render_diagram

    result = analyse(events)
    result.ascii_diagram = render_diagram(result)

    _vlog(args.verbose,
          f"[cascade] root_cause_id={result.root_cause_id}  "
          f"edges={len(result.edges)}  "
          f"severity={result.severity}  "
          f"analysis_ns={result.analysis_ns}")

    # ── Phase 6: agent ────────────────────────────────────────────────────────
    try:
        agent_result = run_agent(
            result,
            provider=provider,
            backend=args.llm_backend,
            model=args.llm_model,
            ollama_host=args.ollama_host,
            no_llm=args.no_llm,
        )
    except Exception as exc:
        print(f"soctriage: agent error: {exc}", file=sys.stderr)
        return EXITERROR

    # ── Phase 7: report ───────────────────────────────────────────────────────
    from soctriage.core.reporter import report

    fmt = args.fmt or "json"
    output_path = getattr(args, "output", None)

    try:
        rendered = report(
            agent_result,
            fmt=fmt,
            output=output_path,
            include_raw=getattr(args, "include_raw", False),
        )
        # If output was requested but file write silently failed (report wraps errors),
        # check if the rendered is an error JSON and the file doesn't exist
        if output_path and not Path(output_path).exists():
            # report() caught a file-write exception — propagate as EXITERROR
            try:
                err_data = json.loads(rendered)
                if "error" in err_data:
                    print(f"soctriage: output error: {err_data['error']}", file=sys.stderr)
                    return EXITERROR
            except Exception:
                pass
    except Exception as exc:
        print(f"soctriage: report error: {exc}", file=sys.stderr)
        return EXITERROR

    if not output_path:
        print(rendered)

    return _exit_code(agent_result)


if __name__ == "__main__":
    sys.exit(main())
