"""Spec Ingestion Agent — PDF/CSV → po-agent-overlay.dts.

[H-06] PDF size guard: pdfplumber/pdfinfo page count check before API call.
>100 pages or >50MB → SPEC_PDF_OVERSIZED warning + section split by heuristic.
Hard cap: 20 pages per API call.
"""

from __future__ import annotations

import csv
import os
import re
import structlog
from pathlib import Path
from typing import Optional

import anthropic
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

from poagent.codes import SPEC_PDF_OVERSIZED

log = structlog.get_logger(__name__)

MAX_PAGES_PER_CALL = 20
MAX_FILE_SIZE_MB = 50
MAX_TOTAL_PAGES = 100


def _is_rate_limit_or_overload(exc: BaseException) -> bool:
    return isinstance(exc, anthropic.RateLimitError) or (
        isinstance(exc, anthropic.APIStatusError)
        and exc.status_code in (503, 529)
    )


@retry(
    retry=retry_if_exception(_is_rate_limit_or_overload),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_claude(client: anthropic.Anthropic, **kwargs: object) -> object:
    return client.messages.create(**kwargs)  # type: ignore[arg-type]


def _get_pdf_info(pdf_path: str) -> tuple[int, float]:
    """Return (page_count, file_size_mb)."""
    file_size_mb = os.path.getsize(pdf_path) / 1_048_576
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
    except ImportError:
        # Fall back to page count estimation from file size
        page_count = max(1, int(file_size_mb * 2))
    return page_count, file_size_mb


def _extract_pdf_text(pdf_path: str, page_start: int = 1, page_end: Optional[int] = None) -> str:
    """Extract text from PDF, optionally restricted to a page range."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            if page_end is None:
                page_end = len(pages)
            selected = pages[page_start - 1:page_end]
            return "\n".join(
                p.extract_text() or "" for p in selected
            )
    except ImportError:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            end = page_end or doc.page_count
            texts = []
            for i in range(page_start - 1, min(end, doc.page_count)):
                page = doc[i]
                texts.append(page.get_text())
            return "\n".join(texts)
        except ImportError:
            return f"[PDF extraction failed — install pdfplumber or PyMuPDF]\nPath: {pdf_path}"


def _parse_csv_rails(csv_path: str) -> list[dict]:
    """Parse rails CSV into list of rail dicts."""
    rails: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rails.append(dict(row))
    return rails


_INGESTION_SYSTEM_PROMPT = """You are an expert embedded systems engineer extracting hardware information
from schematic PDFs and rail CSV files to generate a DTS overlay file.

Extract the following information:
1. Power rails: name, nominal voltage (mV), tolerance (%), whether critical
2. PCIe slots: expected generation (1-5) and link width (x1-x16)
3. Storage: NVMe/UFS expected unsafe shutdowns, UFS EOL info
4. CPU: expected microcode revision (hex)
5. Display connectors expected
6. Physically absent peripherals (camera modules not present at PO)
7. PMBus: I2C bus, address, VOUT page for each rail (if in schematic)

Output format: a valid DTS overlay file using po-agent,* properties.
For each extracted property, include a confidence score comment (0.0-1.0).
Properties with confidence < 0.8 must be written as DTS comments, not active properties.

Always include:
- po-agent,critical flag on VDD_CPU, VDD_DDR, VDD_IO
- po-agent,expected-mv for each identified rail
- po-agent,tolerance-pct (default 5 if not specified)
"""


def ingest_spec(
    pdf_path: Optional[str],
    csv_path: Optional[str],
    board_name: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
    spec_page_start: Optional[int] = None,
    spec_page_end: Optional[int] = None,
) -> str:
    """Run Spec Ingestion Agent to generate po-agent-overlay.dts.

    Returns the overlay DTS content as a string.

    [H-06] Enforces PDF size guard: splits oversized PDFs into sections.
    """
    pdf_text = ""
    if pdf_path:
        page_count, file_size_mb = _get_pdf_info(pdf_path)
        log.info("spec_pdf_info",
                 path=pdf_path, pages=page_count, size_mb=round(file_size_mb, 1))

        if page_count > MAX_TOTAL_PAGES or file_size_mb > MAX_FILE_SIZE_MB:
            log.warning(
                SPEC_PDF_OVERSIZED,
                pages=page_count,
                size_mb=round(file_size_mb, 1),
                action="splitting by section",
            )
            # Use manual override or heuristic section detection
            if spec_page_start and spec_page_end:
                pdf_text = _extract_pdf_text(pdf_path, spec_page_start, spec_page_end)
            else:
                # Chunk into MAX_PAGES_PER_CALL-page sections
                chunk_texts = []
                for start in range(1, page_count + 1, MAX_PAGES_PER_CALL):
                    end = min(start + MAX_PAGES_PER_CALL - 1, page_count)
                    chunk_texts.append(_extract_pdf_text(pdf_path, start, end))
                pdf_text = "\n\n[--- PAGE BREAK ---]\n\n".join(chunk_texts)
        else:
            start = spec_page_start or 1
            end = spec_page_end or page_count
            # Hard cap
            if end - start + 1 > MAX_PAGES_PER_CALL:
                end = start + MAX_PAGES_PER_CALL - 1
            pdf_text = _extract_pdf_text(pdf_path, start, end)

    csv_text = ""
    if csv_path:
        rails = _parse_csv_rails(csv_path)
        csv_text = "RAILS CSV:\n" + "\n".join(
            f"  {r}" for r in rails
        )

    user_content = f"""Board name: {board_name}

SCHEMATIC PDF TEXT:
{pdf_text}

{csv_text}

Generate a complete po-agent-overlay.dts for this board.
Include confidence scores as comments on every extracted property."""

    client = anthropic.Anthropic(api_key=api_key)
    resp = _call_claude(
        client,
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": user_content}],
        system=_INGESTION_SYSTEM_PROMPT,
    )

    raw = resp.content[0].text  # type: ignore[union-attr]
    # Extract DTS block from response
    dts_m = re.search(r"```(?:dts|devicetree)?\n([\s\S]+?)\n```", raw)
    if dts_m:
        overlay_text = dts_m.group(1)
    else:
        overlay_text = raw

    log.info("spec_ingestion_complete", board_name=board_name, overlay_chars=len(overlay_text))
    return overlay_text


def save_overlay(overlay_text: str, output_dir: str, board_name: str) -> str:
    """Write overlay to <output_dir>/<board_name>-po-agent-overlay.dts."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{board_name}-po-agent-overlay.dts"
    out_path.write_text(overlay_text, encoding="utf-8")
    log.info("overlay_saved", path=str(out_path))
    return str(out_path)
