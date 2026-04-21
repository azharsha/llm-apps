"""
html_renderer.py — Phase 7

Self-contained HTML5 report renderer for AgentResult.
No external CSS/JS dependencies — inline styles only.
"""

from __future__ import annotations
import html as _html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soctriage.core.agent_result import AgentResult

__all__ = ["render_html"]

_SEVERITY_COLOURS: dict[str, str] = {
    "critical": "#D32F2F",
    "error":    "#E64A19",
    "warning":  "#F57C00",
    "info":     "#1976D2",
}


def _e(text: object) -> str:
    """HTML-escape a value."""
    return _html.escape(str(text))


def render_html(result: "AgentResult") -> str:
    cascade  = result.cascade
    colour   = _SEVERITY_COLOURS.get(cascade.severity, "#1976D2")

    try:
        import importlib.metadata
        ver = importlib.metadata.version("soctriage")
    except Exception:
        ver = "dev"

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f"<title>SoCTriage — {_e(cascade.chip_gen)}</title>")
    parts.append("<style>")
    parts.append("""
body { font-family: sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
header { padding: 16px 24px; background: #212121; color: #fff; display: flex; align-items: center; gap: 16px; }
header h1 { margin: 0; font-size: 1.2rem; }
.badge { padding: 4px 12px; border-radius: 4px; font-weight: bold; color: #fff; }
.container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
.card { background: #fff; border-radius: 6px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.15); }
.root-cause { border-left: 6px solid """ + colour + """; background: #fff; padding: 16px 20px; border-radius: 4px; margin-bottom: 16px; }
pre { background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 4px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th { background: #424242; color: #fff; padding: 8px 10px; text-align: left; }
td { padding: 7px 10px; border-bottom: 1px solid #e0e0e0; }
tr:nth-child(even) td { background: #fafafa; }
.issue-card { border: 1px solid #e0e0e0; border-radius: 4px; padding: 12px 16px; margin-bottom: 10px; }
details summary { cursor: pointer; font-weight: bold; }
footer { text-align: center; font-size: .8rem; color: #757575; padding: 24px; }
h2 { margin-top: 24px; margin-bottom: 8px; }
ol li { margin-bottom: 6px; }
""")
    parts.append("</style>")
    parts.append("</head>")
    parts.append("<body>")

    # ── Header ────────────────────────────────────────────────────────────────
    parts.append("<header>")
    parts.append("<h1>SoCTriage Report</h1>")
    parts.append(
        f'<span class="badge" style="background-color:{colour}">'
        f"{_e(cascade.severity.upper())}</span>"
    )
    parts.append(
        f"<span>{_e(cascade.chip_gen)} | {_e(cascade.arch)} | "
        f"kernel {_e(cascade.kernel_ver or 'unknown')}</span>"
    )
    parts.append("</header>")

    parts.append('<div class="container">')

    # ── Root Cause ────────────────────────────────────────────────────────────
    parts.append('<div class="root-cause">')
    parts.append("<h2>Root Cause</h2>")
    parts.append(f"<p>{_e(result.root_cause_narrative)}</p>")
    parts.append("</div>")

    # ── Cascade Diagram ───────────────────────────────────────────────────────
    if cascade.ascii_diagram:
        parts.append('<div class="card">')
        parts.append("<h2>Cascade Diagram</h2>")
        parts.append('<pre style="font-family: monospace; white-space: pre">')
        parts.append(_e(cascade.ascii_diagram))
        parts.append("</pre>")
        parts.append("</div>")

    # ── Fix Suggestions ───────────────────────────────────────────────────────
    if result.fix_suggestions:
        parts.append('<div class="card">')
        parts.append("<h2>Fix Suggestions</h2>")
        parts.append("<ol>")
        for fix in result.fix_suggestions:
            parts.append(f"<li>{_e(fix)}</li>")
        parts.append("</ol>")
        parts.append("</div>")

    # ── Known Issues ──────────────────────────────────────────────────────────
    if result.known_issues_matched:
        parts.append('<div class="card">')
        parts.append("<h2>Known Issues</h2>")
        for issue in result.known_issues_matched:
            parts.append('<div class="issue-card">')
            parts.append(f"<strong>{_e(issue.get('issue_id', 'N/A'))}</strong> — "
                         f"{_e(issue.get('title', ''))}")
            if issue.get("fixed_in"):
                parts.append(f"<br>Fixed in: {_e(issue['fixed_in'])}")
            if issue.get("workaround"):
                parts.append(f"<br>Workaround: {_e(issue['workaround'])}")
            parts.append("</div>")
        parts.append("</div>")

    # ── Events Table ──────────────────────────────────────────────────────────
    if cascade.events:
        parts.append('<div class="card">')
        parts.append("<h2>Events</h2>")
        parts.append("<table>")
        parts.append("<thead><tr>")
        for col in ["#", "Type", "Severity", "Subsystem", "IP Block", "Lines", "Conf"]:
            parts.append(f"<th>{col}</th>")
        parts.append("</tr></thead><tbody>")
        for ev in cascade.events:
            parts.append("<tr>")
            parts.append(f"<td>{ev.event_id}</td>")
            parts.append(f"<td>{_e(ev.event_type)}</td>")
            parts.append(f"<td>{_e(ev.severity)}</td>")
            parts.append(f"<td>{_e(ev.subsystem)}</td>")
            parts.append(f"<td>{_e(ev.ip_block)}</td>")
            parts.append(f"<td>{ev.start_line}–{ev.end_line}</td>")
            parts.append(f"<td>{ev.confidence:.2f}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        parts.append("</div>")

    # ── Hardware Contexts ─────────────────────────────────────────────────────
    hw_events = [
        (ev, ev.__dict__.get("hardware_context"))
        for ev in cascade.events
        if ev.__dict__.get("hardware_context") is not None
    ]
    if hw_events:
        parts.append('<div class="card">')
        parts.append("<h2>Hardware Contexts</h2>")
        for ev, hw in hw_events:
            parts.append(f"<h3>Event {ev.event_id} — {_e(ev.event_type)}</h3>")
            if hw is not None and hw.registers:
                parts.append("<table>")
                parts.append("<thead><tr><th>Register</th><th>Raw Value</th><th>Decoded</th></tr></thead><tbody>")
                for reg in hw.registers:
                    decoded_str = ", ".join(f"{k}={v}" for k, v in reg.decoded_fields.items()) or "—"
                    parts.append("<tr>")
                    parts.append(f"<td>{_e(reg.name)}</td>")
                    parts.append(f"<td>0x{reg.raw_value:08X}</td>")
                    parts.append(f"<td>{_e(decoded_str)}</td>")
                    parts.append("</tr>")
                parts.append("</tbody></table>")
        parts.append("</div>")

    # ── Tool Trace ────────────────────────────────────────────────────────────
    if result.tool_trace:
        parts.append('<div class="card">')
        parts.append(f"<details><summary>Tool Trace ({len(result.tool_trace)} calls)</summary>")
        parts.append("<table>")
        parts.append("<thead><tr><th>#</th><th>Tool</th><th>Args</th><th>ms</th></tr></thead><tbody>")
        for tc in result.tool_trace:
            import json as _json
            parts.append("<tr>")
            parts.append(f"<td>{tc.call_index}</td>")
            parts.append(f"<td>{_e(tc.tool_name)}</td>")
            parts.append(f"<td><code>{_e(_json.dumps(tc.arguments))}</code></td>")
            parts.append(f"<td>{tc.duration_ms}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        parts.append("</details>")
        parts.append("</div>")

    # ── Footer ────────────────────────────────────────────────────────────────
    parts.append("</div>")  # close container
    parts.append("<footer>")
    parts.append(
        f"soctriage v{_e(ver)} | {result.total_ms}ms | "
        f"backend: {_e(result.llm_backend)} | model: {_e(result.llm_model)}"
    )
    parts.append("</footer>")
    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)
