"""HTML report generator for PoAgent.

[FINAL-H4] Verdict styling:
  PASS        = #2d6a4f  "PASS — PO SIGN-OFF GRANTED"
  FAIL        = #9b2226  "FAIL — PO SIGN-OFF DENIED"
  CONDITIONAL = #b5451b  "CONDITIONAL — Action Items Required" + orange action box
  INCOMPLETE  = #495057  "Run Incomplete — No PO Verdict"

po_verdict_reason rendered as subtitle.
CONDITIONAL action items box is a rendering REQUIREMENT (not optional styling).
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# Verdict color scheme [FINAL-H4]
VERDICT_STYLES = {
    "PASS": {
        "bg": "#2d6a4f",
        "text": "white",
        "label": "PASS — PO SIGN-OFF GRANTED",
        "icon": "✓",
    },
    "FAIL": {
        "bg": "#9b2226",
        "text": "white",
        "label": "FAIL — PO SIGN-OFF DENIED",
        "icon": "✗",
    },
    "CONDITIONAL": {
        "bg": "#b5451b",
        "text": "white",
        "label": "CONDITIONAL — Action Items Required",
        "icon": "⚠",
    },
    "INCOMPLETE": {
        "bg": "#495057",
        "text": "white",
        "label": "Run Incomplete — No PO Verdict",
        "icon": "—",
    },
}

FINDING_SEVERITY_COLORS = {
    "FAIL": "#9b2226",
    "CONDITIONAL": "#b5451b",
    "WARNING": "#d4a017",
    "INFO": "#4a90d9",
    "PASS": "#2d6a4f",
    "SKIP": "#6c757d",
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>PoAgent Report — {board_name}</title>
  <style>
    body {{ font-family: 'Courier New', monospace; background: #1e1e1e; color: #d4d4d4; margin: 0; padding: 20px; }}
    .verdict-header {{ background: {verdict_bg}; color: {verdict_text}; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
    .verdict-header h1 {{ margin: 0; font-size: 2em; }}
    .verdict-header .subtitle {{ margin: 8px 0 0 0; opacity: 0.9; font-size: 1.1em; }}
    .meta {{ background: #2d2d2d; padding: 16px; border-radius: 8px; margin-bottom: 16px; }}
    .meta table {{ width: 100%; border-collapse: collapse; }}
    .meta td {{ padding: 4px 12px; vertical-align: top; }}
    .meta td:first-child {{ color: #9cdcfe; width: 200px; }}
    .action-items {{ background: #3d2a00; border: 2px solid #b5451b; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
    .action-items h3 {{ color: #f0a050; margin: 0 0 12px 0; }}
    .action-items ul {{ margin: 0; padding-left: 24px; }}
    .action-items li {{ margin: 4px 0; color: #f0c070; }}
    .section {{ background: #2d2d2d; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .section h2 {{ color: #9cdcfe; margin: 0 0 12px 0; border-bottom: 1px solid #444; padding-bottom: 8px; }}
    .domain-result {{ background: #1e1e1e; border: 1px solid #444; border-radius: 6px; padding: 12px; margin-bottom: 12px; }}
    .domain-result h3 {{ margin: 0 0 8px 0; display: flex; justify-content: space-between; }}
    .status-badge {{ border-radius: 4px; padding: 2px 8px; font-size: 0.9em; font-weight: bold; }}
    .status-pass {{ background: #2d6a4f; color: white; }}
    .status-fail {{ background: #9b2226; color: white; }}
    .status-warning {{ background: #d4a017; color: black; }}
    .status-conditional {{ background: #b5451b; color: white; }}
    .status-skip {{ background: #6c757d; color: white; }}
    .status-aborted {{ background: #495057; color: white; }}
    .finding {{ padding: 6px 8px; margin: 4px 0; border-radius: 4px; font-size: 0.9em; }}
    .finding-FAIL {{ background: rgba(155,34,38,0.2); border-left: 3px solid #9b2226; }}
    .finding-CONDITIONAL {{ background: rgba(181,69,27,0.2); border-left: 3px solid #b5451b; }}
    .finding-WARNING {{ background: rgba(212,160,23,0.2); border-left: 3px solid #d4a017; }}
    .finding-INFO {{ background: rgba(74,144,217,0.2); border-left: 3px solid #4a90d9; }}
    .finding-PASS {{ background: rgba(45,106,79,0.2); border-left: 3px solid #2d6a4f; }}
    .hypothesis {{ background: #252525; border: 1px solid #555; border-radius: 6px; padding: 12px; margin-bottom: 8px; }}
    .confidence {{ color: #9cdcfe; font-size: 0.9em; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }}
    .tag {{ background: #3a3a3a; color: #ccc; border-radius: 3px; padding: 1px 6px; font-size: 0.8em; }}
    .ecc-section table {{ border-collapse: collapse; width: 100%; }}
    .ecc-section td, .ecc-section th {{ padding: 6px 12px; border: 1px solid #444; }}
    .ecc-section th {{ background: #333; color: #9cdcfe; }}
    code {{ background: #333; padding: 1px 4px; border-radius: 3px; }}
    .signature {{ font-size: 0.8em; color: #666; margin-top: 24px; border-top: 1px solid #333; padding-top: 12px; }}
  </style>
</head>
<body>

<div class="verdict-header">
  <h1>{verdict_icon} {verdict_label}</h1>
  <div class="subtitle">{po_verdict_reason}</div>
</div>

{action_items_html}

<div class="meta">
  <table>
    <tr><td>Board</td><td>{board_name}</td></tr>
    <tr><td>Run ID</td><td>{run_id}</td></tr>
    <tr><td>Timestamp</td><td>{timestamp}</td></tr>
    <tr><td>Schema Version</td><td>{schema_version}</td></tr>
    <tr><td>Silicon Stepping</td><td>{silicon_stepping}</td></tr>
    <tr><td>Kernel Version</td><td>{kernel_version}</td></tr>
    <tr><td>ECC Source</td><td>{ecc_source}</td></tr>
  </table>
</div>

{preflight_section}

{root_cause_section}

{domain_results_section}

{ecc_section}

{boot_context_section}

<div class="signature">
  PoAgent v5.8 | Generated: {generated_at} | {signature_info}
</div>

<!-- poagent-hmac-sha256: {hmac_placeholder} -->
</body>
</html>
"""


def _status_badge(status: str) -> str:
    cls = f"status-{status.replace('_', '-').lower()}"
    return f'<span class="status-badge {cls}">{html.escape(status.upper())}</span>'


def _severity_class(severity: str) -> str:
    return f"finding-{severity.upper()}"


def _render_action_items(action_items: list[str], verdict: str) -> str:
    """Render mandatory CONDITIONAL action items box. [FINAL-H4]"""
    if verdict != "CONDITIONAL" or not action_items:
        return ""
    items_html = "\n".join(
        f"<li>{html.escape(item)}</li>" for item in action_items
    )
    return f"""<div class="action-items">
  <h3>⚠ Required Action Items (CONDITIONAL verdict)</h3>
  <ul>
{items_html}
  </ul>
</div>
"""


def _render_preflight(preflight_report: Optional[object]) -> str:
    if preflight_report is None:
        return ""
    gates = getattr(preflight_report, "gates", [])
    if not gates:
        return ""
    rows = ""
    for g in gates:
        icon = "✓" if g.passed else ("—" if g.severity == "SKIP" else "✗")
        color = "#2d6a4f" if g.passed else ("#d4a017" if g.severity == "WARNING" else "#9b2226")
        rows += (
            f"<tr><td>Gate {g.gate_num}</td>"
            f"<td>{html.escape(g.name)}</td>"
            f"<td style='color:{color}'>{icon} {html.escape(g.severity)}</td>"
            f"<td>{html.escape(g.detail[:100])}</td></tr>\n"
        )
    return f"""<div class="section">
  <h2>Pre-Flight Gates</h2>
  <table style="width:100%;border-collapse:collapse">
    <tr><th style="text-align:left;padding:4px 8px;background:#333">Gate</th>
        <th style="text-align:left;padding:4px 8px;background:#333">Name</th>
        <th style="text-align:left;padding:4px 8px;background:#333">Status</th>
        <th style="text-align:left;padding:4px 8px;background:#333">Detail</th></tr>
{rows}  </table>
</div>
"""


def _render_root_causes(hypotheses: list) -> str:
    if not hypotheses:
        return ""
    items = ""
    for i, h in enumerate(hypotheses, 1):
        hypothesis = getattr(h, "hypothesis", str(h))
        confidence = getattr(h, "confidence", 0.0)
        affected = getattr(h, "affected_domains", [])
        actions = getattr(h, "actions", [])
        actions_html = ""
        if actions:
            actions_html = "<ul>" + "".join(
                f"<li>{html.escape(a)}</li>" for a in actions
            ) + "</ul>"
        domains_str = ", ".join(html.escape(d) for d in affected) or "—"
        items += f"""<div class="hypothesis">
  <b>#{i}</b> {html.escape(hypothesis)}
  <div class="confidence">Confidence: {confidence:.0%} | Domains: {domains_str}</div>
  {actions_html}
</div>
"""
    return f"""<div class="section">
  <h2>Root Cause Hypotheses</h2>
{items}
</div>
"""


def _render_domain_results(domain_results: list[dict]) -> str:
    if not domain_results:
        return ""
    items = ""
    for dr in domain_results:
        domain = dr.get("domain", "unknown")
        status = dr.get("status", "unknown")
        summary = dr.get("summary", "")
        findings = dr.get("top_findings", [])
        hypothesis = dr.get("root_cause_hypothesis", "")
        timed_out = dr.get("timed_out_probes", [])
        tags = dr.get("confidence_tags", [])

        findings_html = ""
        for f in findings:
            sev = f.get("severity", "INFO")
            code = f.get("code", "")
            msg = f.get("message", "")
            cls = _severity_class(sev)
            findings_html += (
                f'<div class="finding {cls}">'
                f'<code>{html.escape(sev)}</code> '
                f'<code>{html.escape(code)}</code> '
                f'— {html.escape(msg[:200])}'
                f'</div>\n'
            )

        tags_html = ""
        if tags:
            tags_html = '<div class="tags">' + "".join(
                f'<span class="tag">{html.escape(t)}</span>' for t in tags
            ) + "</div>"

        timeout_html = ""
        if timed_out:
            timeout_html = (
                f'<div style="color:#d4a017;font-size:0.85em;margin-top:6px">'
                f'⏱ Timed out: {", ".join(html.escape(t) for t in timed_out)}'
                f'</div>'
            )

        hypothesis_html = ""
        if hypothesis:
            hypothesis_html = (
                f'<div style="font-size:0.9em;color:#ccc;margin-top:8px">'
                f'<em>Hypothesis:</em> {html.escape(hypothesis[:300])}'
                f'</div>'
            )

        items += f"""<div class="domain-result">
  <h3>
    <span>{html.escape(domain.upper().replace("_", " "))}</span>
    {_status_badge(status)}
  </h3>
  <div style="font-size:0.9em;color:#999;margin-bottom:8px">{html.escape(summary[:300])}</div>
  {findings_html}
  {hypothesis_html}
  {timeout_html}
  {tags_html}
</div>
"""
    return f"""<div class="section">
  <h2>Domain Results</h2>
{items}
</div>
"""


def _render_ecc_section(triage_output: object) -> str:
    ecc_not_monitorable = getattr(triage_output, "ecc_not_monitorable", False)
    ce_t0 = getattr(triage_output, "ecc_correctable_t0", None)
    ce_t1 = getattr(triage_output, "ecc_correctable_t1", None)
    ce_delta = getattr(triage_output, "ecc_correctable_delta", None)
    ce_rate = getattr(triage_output, "ecc_rate_per_min", None)
    ue_delta = getattr(triage_output, "ecc_uncorrectable_delta", None)
    dram_marginal = getattr(triage_output, "dram_marginal", False)
    dram_unc = getattr(triage_output, "dram_uncorrectable", False)

    if ecc_not_monitorable:
        status_color = "#d4a017"
        status_text = "ECC monitoring unavailable on this platform"
    elif dram_unc:
        status_color = "#9b2226"
        status_text = "DRAM_UNCORRECTABLE_ERROR — hard FAIL"
    elif dram_marginal:
        status_color = "#b5451b"
        status_text = "DRAM_MARGINAL — correctable error rate elevated"
    elif ce_t0 is not None:
        status_color = "#2d6a4f"
        status_text = "PASS — ECC delta within normal limits"
    else:
        return ""

    rows = ""
    for label, value in [
        ("CE at t0", ce_t0), ("CE at t1", ce_t1),
        ("CE delta", ce_delta), ("CE rate (per min)", ce_rate),
        ("UE delta", ue_delta),
    ]:
        val_str = str(value) if value is not None else "N/A"
        rows += f"<tr><td>{label}</td><td>{html.escape(val_str)}</td></tr>\n"

    return f"""<div class="section ecc-section">
  <h2>DRAM / ECC Status</h2>
  <div style="color:{status_color};margin-bottom:12px"><b>{status_text}</b></div>
  <table><tr><th>Metric</th><th>Value</th></tr>
{rows}  </table>
</div>
"""


def _render_boot_context(boot_context_meta: dict) -> str:
    if not boot_context_meta:
        return ""
    rows = ""
    for key, value in list(boot_context_meta.items())[:20]:
        if key in ("dmesg", "dmesg_raw"):
            continue
        val_str = str(value)[:200]
        rows += (
            f"<tr><td style='color:#9cdcfe;width:220px'>{html.escape(key)}</td>"
            f"<td>{html.escape(val_str)}</td></tr>\n"
        )
    return f"""<div class="section">
  <h2>Boot Context</h2>
  <table style="width:100%;border-collapse:collapse">
{rows}  </table>
</div>
"""


def generate_html_report(
    triage_output: object,
    preflight_report: Optional[object] = None,
    boot_context: Optional[dict] = None,
    run_id: str = "",
    signing_key_id: str = "",
) -> str:
    """Generate the full HTML report from TriageOutput.

    Returns the HTML string (without HMAC signature — that's added by signing.py).
    """
    verdict = getattr(triage_output, "po_verdict", "INCOMPLETE")
    verdict_style = VERDICT_STYLES.get(verdict, VERDICT_STYLES["INCOMPLETE"])
    board_name = getattr(triage_output, "board_name", "unknown")
    schema_version = getattr(triage_output, "schema_version", "5.8")
    po_verdict_reason = getattr(triage_output, "po_verdict_reason", "")
    action_items = getattr(triage_output, "action_items", [])
    hypotheses = getattr(triage_output, "root_cause_hypotheses", [])
    domain_summaries = getattr(triage_output, "domain_summaries", [])
    recommended_actions = getattr(triage_output, "recommended_actions", [])
    boot_context_meta = getattr(triage_output, "boot_context_meta", {})
    silicon_unresolved = getattr(triage_output, "silicon_stepping_unresolved", False)
    dmesg_k = getattr(triage_output, "dmesg_supports_k", True)

    # Silicon stepping info
    stepping = (boot_context or {}).get("silicon_stepping", {})
    if silicon_unresolved:
        silicon_str = f'<span style="color:#d4a017">UNRESOLVED (source: fallback)</span>'
    else:
        silicon_str = html.escape(
            f"{stepping.get('platform', 'unknown')} / {stepping.get('raw', 'N/A')}"
        )

    kernel_version = (boot_context or {}).get("kernel_version", "unknown")
    if not dmesg_k:
        kernel_version += " (dmesg -k not supported)"

    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(getattr(triage_output, "timestamp", time.time()))
    )

    ecc_source = (boot_context or {}).get("edac_source", "unknown")

    signature_info = ""
    if signing_key_id:
        signature_info = f"Signing key ID: {html.escape(signing_key_id)}"

    html_content = _HTML_TEMPLATE.format(
        board_name=html.escape(board_name),
        run_id=html.escape(run_id or getattr(triage_output, "run_id", "")),
        timestamp=timestamp,
        schema_version=html.escape(schema_version),
        verdict_bg=verdict_style["bg"],
        verdict_text=verdict_style["text"],
        verdict_icon=verdict_style["icon"],
        verdict_label=verdict_style["label"],
        po_verdict_reason=html.escape(po_verdict_reason),
        action_items_html=_render_action_items(action_items, verdict),
        silicon_stepping=silicon_str,
        kernel_version=html.escape(str(kernel_version)),
        ecc_source=html.escape(str(ecc_source)),
        preflight_section=_render_preflight(preflight_report),
        root_cause_section=_render_root_causes(hypotheses),
        domain_results_section=_render_domain_results(domain_summaries),
        ecc_section=_render_ecc_section(triage_output),
        boot_context_section=_render_boot_context(boot_context_meta),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        signature_info=signature_info,
        hmac_placeholder="",  # filled in by signing.py
    )

    return html_content


def save_html_report(
    html_content: str,
    output_dir: str,
    run_id: str,
) -> str:
    """Save HTML report to file. Returns path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}_report.html"
    out_path.write_text(html_content, encoding="utf-8")
    log.info("html_report_saved", path=str(out_path))
    return str(out_path)


def save_json_report(
    triage_output: object,
    output_dir: str,
    run_id: str,
) -> str:
    """Save JSON triage report. Returns path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}_triage.json"
    if hasattr(triage_output, "to_json"):
        json_str = triage_output.to_json()
    else:
        import dataclasses
        json_str = json.dumps(
            dataclasses.asdict(triage_output) if dataclasses.is_dataclass(triage_output)
            else triage_output,
            indent=2, default=str
        )
    out_path.write_text(json_str, encoding="utf-8")
    log.info("json_report_saved", path=str(out_path))
    return str(out_path)
