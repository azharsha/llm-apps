"""CLI wrapper for the Spec Ingestion Agent [H-06].

Provides a standalone entry point for ingesting board specification
PDFs and CSVs outside of a full PoAgent run. Outputs a JSON overlay
snippet that can be merged with an existing overlay file.

Usage:
    python -m poagent.agents.ingester --pdf spec.pdf --csv rails.csv --out overlay_patch.json

[H-06] PDF size guard: >100 pages or >50MB → section split mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import structlog

from poagent.security.credentials import resolve_api_key

log = structlog.get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poagent-ingest",
        description="Spec Ingestion Agent — extract board constraints from PDF/CSV specs.",
    )
    p.add_argument("--pdf", metavar="PATH", help="Board spec PDF path.")
    p.add_argument("--csv", metavar="PATH", help="Rail/power spec CSV path.")
    p.add_argument(
        "--page-range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Page range for PDF (1-based inclusive). Required for large PDFs.",
    )
    p.add_argument(
        "--out",
        metavar="PATH",
        default="overlay_patch.json",
        help="Output overlay JSON patch path (default: overlay_patch.json).",
    )
    p.add_argument(
        "--merge",
        metavar="PATH",
        help="Existing overlay JSON/YAML to merge patch into.",
    )
    p.add_argument(
        "--api-key",
        metavar="KEY",
        help="Anthropic API key. Falls back to ANTHROPIC_API_KEY env.",
    )
    p.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model for ingestion (default: claude-sonnet-4-6).",
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return p


def _parse_csv_rails(csv_path: Path) -> dict:
    """Parse rail spec CSV into overlay-compatible rail dict.

    Expected columns: name, expected_mv, tolerance_pct, pmbus_addr (optional)
    Returns dict keyed by rail name.
    """
    import csv

    rails: dict = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue
            rail: dict = {}
            if "expected_mv" in row:
                try:
                    rail["expected_mv"] = int(row["expected_mv"].strip())
                except ValueError:
                    pass
            if "tolerance_pct" in row:
                try:
                    rail["tolerance_pct"] = float(row["tolerance_pct"].strip())
                except ValueError:
                    pass
            if "pmbus_addr" in row and row["pmbus_addr"].strip():
                rail["pmbus_addr"] = row["pmbus_addr"].strip()
            if "critical" in row:
                rail["critical"] = row["critical"].strip().lower() in ("1", "true", "yes")
            rails[name] = rail

    log.info("csv_rails_parsed", count=len(rails), path=str(csv_path))
    return rails


def _merge_overlays(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base. Lists are replaced, dicts are merged."""
    result = dict(base)
    for key, val in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _merge_overlays(result[key], val)
        else:
            result[key] = val
    return result


def main(argv: list[str] | None = None) -> int:
    import logging

    parser = _build_parser()
    args = parser.parse_args(argv)

    level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, stream=sys.stderr)

    if not args.pdf and not args.csv:
        print("ERROR: At least one of --pdf or --csv is required.", file=sys.stderr)
        return 1

    api_key = resolve_api_key(cli_key=getattr(args, "api_key", None))
    if not api_key and args.pdf:
        print("ERROR: --api-key or ANTHROPIC_API_KEY is required for PDF ingestion.", file=sys.stderr)
        return 1

    patch: dict = {}

    # PDF ingestion
    if args.pdf:
        from poagent.board.spec_parser import ingest_spec

        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
            return 1

        page_range = tuple(args.page_range) if args.page_range else None
        print(f"Ingesting PDF: {pdf_path}")
        try:
            pdf_result = ingest_spec(
                pdf_path=pdf_path,
                api_key=api_key,
                model=args.model,
                page_range=page_range,
            )
            patch.update(pdf_result)
            print(f"  Pages processed: {pdf_result.get('pages_processed', '?')}")
            print(f"  Rails extracted: {len(pdf_result.get('rails', {}))}")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: PDF ingestion failed: {exc}", file=sys.stderr)
            return 1

    # CSV ingestion
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"ERROR: CSV not found: {args.csv}", file=sys.stderr)
            return 1

        print(f"Ingesting CSV: {csv_path}")
        try:
            csv_rails = _parse_csv_rails(csv_path)
            existing_rails = patch.get("rails", {})
            patch["rails"] = _merge_overlays(existing_rails, csv_rails)
            print(f"  Rails from CSV: {len(csv_rails)}")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: CSV ingestion failed: {exc}", file=sys.stderr)
            return 1

    # Merge with existing overlay
    if args.merge:
        merge_path = Path(args.merge)
        if not merge_path.exists():
            print(f"ERROR: Merge overlay not found: {args.merge}", file=sys.stderr)
            return 1

        import yaml as _yaml

        text = merge_path.read_text(encoding="utf-8")
        try:
            base = json.loads(text)
        except ValueError:
            base = _yaml.safe_load(text) or {}

        patch = _merge_overlays(base, patch)
        print(f"Merged with existing overlay: {args.merge}")

    # Write output
    out_path = Path(args.out)
    out_path.write_text(json.dumps(patch, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Overlay patch written: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
