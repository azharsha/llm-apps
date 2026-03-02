"""
HTML report generation for port_agent porting sessions.
"""
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, BaseLoader

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Kernel Porting Report — {{ timestamp }}</title>
  <style>
    body { font-family: 'Segoe UI', sans-serif; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; background: #0d1117; color: #c9d1d9; }
    h1 { color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem; }
    h2 { color: #79c0ff; margin-top: 2rem; }
    .meta { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 1rem; margin-bottom: 1.5rem; }
    .meta dt { font-weight: bold; color: #8b949e; float: left; width: 200px; }
    .meta dd { margin-left: 200px; color: #c9d1d9; margin-bottom: 0.3rem; }
    .summary { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 1rem 1.5rem; white-space: pre-wrap; font-family: monospace; font-size: 0.9rem; line-height: 1.5; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th { background: #21262d; padding: 0.6rem 1rem; text-align: left; border: 1px solid #30363d; color: #8b949e; font-size: 0.85rem; }
    td { padding: 0.5rem 1rem; border: 1px solid #30363d; font-size: 0.9rem; vertical-align: top; }
    tr:nth-child(even) td { background: #161b22; }
    .badge-ok  { background: #1f6a2e; color: #56d364; border-radius: 4px; padding: 1px 6px; font-size: 0.8rem; }
    .badge-skip { background: #5a3a1a; color: #e3b341; border-radius: 4px; padding: 1px 6px; font-size: 0.8rem; }
    .hash { font-family: monospace; font-size: 0.85rem; color: #58a6ff; }
    .stats { display: flex; gap: 1rem; margin: 1rem 0; }
    .stat  { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 1rem 1.5rem; flex: 1; text-align: center; }
    .stat .num { font-size: 2rem; font-weight: bold; color: #58a6ff; }
    .stat .lbl { font-size: 0.85rem; color: #8b949e; }
  </style>
</head>
<body>
  <h1>Kernel Porting Report</h1>

  <div class="meta">
    <dl>
      <dt>Timestamp</dt><dd>{{ timestamp }}</dd>
      <dt>Upstream</dt><dd>{{ result.upstream_path }} @ {{ result.upstream_branch }}</dd>
      <dt>Downstream</dt><dd>{{ result.downstream_path }} @ {{ result.downstream_branch }}</dd>
      <dt>Work Branch</dt><dd>{{ result.work_branch }}</dd>
      <dt>Directories</dt><dd>{{ result.dirs | join(', ') }}</dd>
      <dt>Build Command</dt><dd>{{ result.build_cmd or '(none — checkpatch only)' }}</dd>
      <dt>Dry Run</dt><dd>{{ 'Yes' if result.dry_run else 'No' }}</dd>
      <dt>Agent Iterations</dt><dd>{{ result.iterations }}</dd>
    </dl>
  </div>

  <div class="stats">
    <div class="stat"><div class="num">{{ result.ported_commits | length }}</div><div class="lbl">Ported</div></div>
    <div class="stat"><div class="num">{{ result.skipped_commits | length }}</div><div class="lbl">Skipped</div></div>
    <div class="stat"><div class="num">{{ result.tools_used | length }}</div><div class="lbl">Tool Calls</div></div>
  </div>

  <h2>Agent Summary</h2>
  <div class="summary">{{ result.summary }}</div>

  {% if result.ported_commits %}
  <h2>Ported Commits</h2>
  <table>
    <tr><th>New Hash</th><th>Details</th></tr>
    {% for c in result.ported_commits %}
    <tr>
      <td class="hash">{{ c.new_hash[:12] if c.new_hash else 'N/A' }}</td>
      <td>{{ c.tool_input }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  {% if result.skipped_commits %}
  <h2>Skipped Commits</h2>
  <table>
    <tr><th>Hash</th><th>Reason</th></tr>
    {% for c in result.skipped_commits %}
    <tr>
      <td class="hash"><span class="badge-skip">SKIP</span> {{ c.hash[:12] if c.hash else 'N/A' }}</td>
      <td>{{ c.reason }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

</body>
</html>
"""


def generate_html_report(result: dict, output_path: str | None = None) -> str:
    """
    Generate an HTML report from a porting session result dict.
    Returns the HTML string and optionally writes to output_path.
    """
    timestamp = result.get("timestamp", datetime.now().isoformat())
    # Add branch info if not present
    result.setdefault("upstream_branch", "unknown")
    result.setdefault("downstream_branch", "unknown")

    env = Environment(autoescape=True, loader=BaseLoader())
    tmpl = env.from_string(_TEMPLATE)
    html = tmpl.render(result=result, timestamp=timestamp)

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html
