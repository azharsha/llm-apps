"""
HTML digest generator for LKML patch summaries.

Parses the structured text produced by the agent and renders it as a
readable, dark-themed HTML report.
"""
import re
from datetime import datetime, timezone
from jinja2 import Template

from config import MODEL


# ---------------------------------------------------------------------------
# Structured section parser
# ---------------------------------------------------------------------------

def _parse_digest_sections(digest_text: str) -> list[dict]:
    """
    Extract individual patch/series sections from the agent's digest.

    Each section starts with ``### [SUBSYSTEM] — <title>`` and ends at the
    next ``---`` separator or the end of the digest.

    Returns a list of dicts:
        subsystem, title, submitter, type_, impact, patches_count,
        state, web_url, summary, key_files, flags, raw
    """
    # Slice to the content between the digest delimiters
    match = re.search(
        r"=== LKML DIGEST BEGIN ===(.*?)=== LKML DIGEST END ===",
        digest_text,
        re.DOTALL,
    )
    body = match.group(1) if match else digest_text

    # Split on "---" separators
    chunks = re.split(r"\n---\n", body)

    sections = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Must start with a ### heading to be a patch section
        heading = re.match(r"###\s+\[(.+?)\]\s+[—–-]+\s+(.+)", chunk)
        if not heading:
            continue

        subsystem = heading.group(1).strip()
        title = heading.group(2).strip()

        def _field(name: str) -> str:
            # [: ]+ avoids crossing newlines (unlike [\s]+)
            m = re.search(rf"\*\*{re.escape(name)}\*\*[: ]+([^\n]+)", chunk)
            return m.group(1).strip() if m else ""

        def _block(name: str) -> str:
            """Extract a multi-line block that follows **Name**:"""
            m = re.search(
                rf"\*\*{re.escape(name)}\*\*:\s*\n(.*?)(?=\n\*\*|\Z)",
                chunk,
                re.DOTALL,
            )
            return m.group(1).strip() if m else _field(name)

        # Parse flags — may be "NONE" or a bullet list
        flags_raw = _block("Flags")
        if flags_raw.upper().startswith("NONE"):
            flags = []
        else:
            flags = [
                ln.lstrip("-• ").strip()
                for ln in flags_raw.splitlines()
                if ln.strip() and not ln.strip().upper().startswith("NONE")
            ]

        # Parse memory leak flags — same structure as ABI flags
        leaks_raw = _block("Memory Leaks")
        if leaks_raw.upper().startswith("NONE"):
            memory_leaks = []
        else:
            memory_leaks = [
                ln.lstrip("-• ").strip()
                for ln in leaks_raw.splitlines()
                if ln.strip() and not ln.strip().upper().startswith("NONE")
            ]

        # Key files as a list
        files_raw = _field("Key files")
        key_files = [f.strip().strip("`,'") for f in re.split(r"[,`]+", files_raw) if f.strip().strip("`,'")]

        # Patches count from "N patch(es)"
        patches_str = _field("Patches")
        patches_count_m = re.search(r"(\d+)", patches_str)
        patches_count = int(patches_count_m.group(1)) if patches_count_m else 1

        sections.append({
            "subsystem": subsystem,
            "title": title,
            "submitter": _field("Submitter"),
            "type_": _field("Type"),
            "impact": _field("Impact"),
            "patches_count": patches_count,
            "state": _field("State") or _field("Patches").split("**State**:")[-1].strip(),
            "web_url": _field("Web"),
            "summary": _block("Summary"),
            "key_files": key_files,
            "flags": flags,
            "memory_leaks": memory_leaks,
            "raw": chunk,
        })

    return sections


# ---------------------------------------------------------------------------
# Header stats parser
# ---------------------------------------------------------------------------

def _parse_header_stats(digest_text: str) -> dict:
    """Extract the Date / Patches Fetched / Series Summarised header."""
    date_m = re.search(r"Date:\s*(.+)", digest_text)
    fetched_m = re.search(r"Patches Fetched:\s*(\d+)", digest_text)
    series_m = re.search(r"Series Summarised:\s*(\d+)", digest_text)
    return {
        "date": date_m.group(1).strip() if date_m else "—",
        "patches_fetched": fetched_m.group(1) if fetched_m else "—",
        "series_count": series_m.group(1) if series_m else "—",
    }


# ---------------------------------------------------------------------------
# Jinja2 HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LKML Patch Digest — {{ generated_at }}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: #0d1117;
      color: #c9d1d9;
      margin: 0;
      padding: 24px 16px;
      line-height: 1.6;
    }
    a { color: #58a6ff; text-decoration: none; }
    a:hover { text-decoration: underline; }
    h1 { color: #f0f6fc; font-size: 1.7em; margin-bottom: 4px; }
    h2 { color: #58a6ff; font-size: 1.15em; margin: 0 0 8px; }
    .tagline { color: #8b949e; font-size: 0.9em; margin-bottom: 24px; }

    /* ── Stats bar ── */
    .stats {
      display: flex; flex-wrap: wrap; gap: 16px;
      background: #161b22; border: 1px solid #30363d;
      border-radius: 10px; padding: 16px 24px; margin-bottom: 28px;
    }
    .stat { text-align: center; min-width: 80px; }
    .stat-value { font-size: 2em; font-weight: 700; color: #58a6ff; }
    .stat-label { font-size: 0.75em; color: #8b949e; text-transform: uppercase; letter-spacing: .05em; }

    /* ── Section filter bar ── */
    .filters { margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 8px; }
    .filter-btn {
      background: #21262d; border: 1px solid #30363d; border-radius: 20px;
      color: #c9d1d9; cursor: pointer; font-size: 0.8em; padding: 4px 14px;
      transition: background 0.15s;
    }
    .filter-btn:hover, .filter-btn.active { background: #1f6feb; border-color: #1f6feb; color: #fff; }

    /* ── Patch cards ── */
    .card {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 10px; padding: 18px 20px; margin-bottom: 18px;
      transition: border-color 0.15s;
    }
    .card:hover { border-color: #58a6ff; }
    .card.flagged { border-left: 4px solid #da3633; }
    .card.impact-major { border-top: 3px solid #f85149; }
    .card.impact-moderate { border-top: 3px solid #d29922; }
    .card.impact-minor { border-top: 3px solid #3fb950; }

    .card-header { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; margin-bottom: 10px; }
    .tag {
      border-radius: 4px; font-size: 0.75em; font-weight: 600;
      padding: 2px 10px; white-space: nowrap;
    }
    .tag-subsystem { background: #1f6feb; color: #fff; }
    .tag-type     { background: #21262d; border: 1px solid #444c56; color: #8b949e; }
    .tag-impact-major    { background: #3d1f1f; color: #f85149; }
    .tag-impact-moderate { background: #2d2208; color: #d29922; }
    .tag-impact-minor    { background: #0f2417; color: #3fb950; }

    h2.card-title { font-size: 1em; color: #f0f6fc; margin: 4px 0 8px; }
    .meta { color: #8b949e; font-size: 0.82em; margin-bottom: 10px; }
    .summary { margin-bottom: 12px; font-size: 0.93em; }

    .files { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
    .file-tag {
      background: #0d1117; border: 1px solid #30363d;
      border-radius: 4px; font-family: monospace; font-size: 0.78em;
      padding: 1px 7px; color: #79c0ff;
    }

    .flags-list { margin: 0; padding: 0; list-style: none; }
    .flag-item {
      background: #3d1f1f; border: 1px solid #da3633;
      border-radius: 4px; color: #f85149;
      display: inline-block; font-size: 0.78em;
      margin: 2px; padding: 2px 9px;
    }
    .leak-item {
      background: #2b1d00; border: 1px solid #d29922;
      border-radius: 4px; color: #e3b341;
      display: inline-block; font-size: 0.78em;
      margin: 2px; padding: 2px 9px;
    }
    .card.leaked { border-left: 4px solid #d29922; }

    /* ── Raw digest fallback ── */
    .raw-digest {
      background: #0d1117; border: 1px solid #30363d;
      border-radius: 8px; font-family: monospace; font-size: 0.85em;
      max-height: 600px; overflow-y: auto; padding: 16px;
      white-space: pre-wrap; word-break: break-word;
    }
    details > summary { cursor: pointer; color: #8b949e; font-size: 0.85em; margin-top: 24px; }

    footer { color: #6e7681; font-size: 0.78em; margin-top: 32px; text-align: center; }
  </style>
</head>
<body>

<h1>🐧 LKML Patch Digest</h1>
<p class="tagline">
  Generated {{ generated_at }} &nbsp;·&nbsp; Model: {{ model }}
  &nbsp;·&nbsp; {{ api_calls }} API calls &nbsp;·&nbsp; {{ iterations }} agent turns
</p>

<div class="stats">
  <div class="stat">
    <div class="stat-value">{{ patches_fetched }}</div>
    <div class="stat-label">Patches fetched</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ series_count }}</div>
    <div class="stat-label">Series analysed</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ sections|length }}</div>
    <div class="stat-label">In digest</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ flagged_count }}</div>
    <div class="stat-label">ABI flagged</div>
  </div>
  <div class="stat">
    <div class="stat-value">{{ leak_count }}</div>
    <div class="stat-label">Leak concerns</div>
  </div>
</div>

{% if sections %}
<div class="filters" id="filters">
  <button class="filter-btn active" onclick="filterCards('all', this)">All</button>
  <button class="filter-btn" onclick="filterCards('flagged', this)">⚠ ABI flagged</button>
  <button class="filter-btn" onclick="filterCards('leaked', this)">⚠ Memory leaks</button>
  <button class="filter-btn" onclick="filterCards('impact-major', this)">Major impact</button>
  {% for sub in subsystems %}
  <button class="filter-btn" onclick="filterCards('sub-{{ sub|lower|replace(" ", "-")|replace("/", "-") }}', this)">{{ sub }}</button>
  {% endfor %}
</div>

<div id="cards">
{% for s in sections %}
{% set impact_cls = "impact-" + s.impact|lower %}
{% set sub_cls = "sub-" + s.subsystem|lower|replace(" ", "-")|replace("/", "-") %}
<div class="card {{ impact_cls }} {% if s.flags %}flagged{% endif %} {% if s.memory_leaks %}leaked{% endif %} {{ sub_cls }}" data-impact="{{ s.impact|lower }}" data-sub="{{ sub_cls }}" data-flagged="{{ 'yes' if s.flags else 'no' }}" data-leaked="{{ 'yes' if s.memory_leaks else 'no' }}">
  <div class="card-header">
    <span class="tag tag-subsystem">{{ s.subsystem }}</span>
    {% if s.type_ %}<span class="tag tag-type">{{ s.type_ }}</span>{% endif %}
    <span class="tag tag-impact-{{ s.impact|lower }}">{{ s.impact }}</span>
  </div>

  <h2 class="card-title">
    {% if s.web_url %}<a href="{{ s.web_url }}" target="_blank">{{ s.title }}</a>{% else %}{{ s.title }}{% endif %}
  </h2>

  <p class="meta">
    <strong>Submitter</strong>: {{ s.submitter }}
    &nbsp;·&nbsp; <strong>Patches</strong>: {{ s.patches_count }}
    {% if s.state %}&nbsp;·&nbsp; <strong>State</strong>: {{ s.state }}{% endif %}
  </p>

  <div class="summary">{{ s.summary }}</div>

  {% if s.key_files %}
  <div class="files">
    {% for f in s.key_files %}<span class="file-tag">{{ f }}</span>{% endfor %}
  </div>
  {% endif %}

  {% if s.flags %}
  <ul class="flags-list">
    {% for flag in s.flags %}<li class="flag-item">⚠ {{ flag }}</li>{% endfor %}
  </ul>
  {% endif %}

  {% if s.memory_leaks %}
  <div style="margin-top:6px;">
    <span style="font-size:0.78em;color:#8b949e;">Memory leaks:</span>
    <ul class="flags-list">
      {% for leak in s.memory_leaks %}<li class="leak-item">⚠ {{ leak }}</li>{% endfor %}
    </ul>
  </div>
  {% endif %}
</div>
{% endfor %}
</div>
{% else %}
<p style="color:#8b949e;">No structured sections could be parsed — see raw digest below.</p>
{% endif %}

<details>
  <summary>Raw agent digest (click to expand)</summary>
  <div class="raw-digest">{{ raw_digest }}</div>
</details>

<footer>
  LKML Patch Summary Agent &nbsp;·&nbsp; Powered by {{ model }}
</footer>

<script>
function filterCards(filter, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#cards .card').forEach(card => {
    if (filter === 'all') {
      card.style.display = '';
    } else if (filter === 'flagged') {
      card.style.display = card.dataset.flagged === 'yes' ? '' : 'none';
    } else if (filter === 'leaked') {
      card.style.display = card.dataset.leaked === 'yes' ? '' : 'none';
    } else if (filter === 'impact-major') {
      card.style.display = card.dataset.impact === 'major' ? '' : 'none';
    } else {
      card.style.display = card.dataset.sub === filter ? '' : 'none';
    }
  });
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_html_report(result: dict, output_path: str) -> None:
    """
    Render the agent result dict as an HTML file.

    Args:
        result:      Dict returned by orchestrator.run_analysis().
        output_path: Absolute path to write the HTML file.
    """
    digest_text = result.get("digest", "")
    sections = _parse_digest_sections(digest_text)
    header = _parse_header_stats(digest_text)

    subsystems = list(dict.fromkeys(s["subsystem"] for s in sections))  # preserve order
    flagged_count = sum(1 for s in sections if s["flags"])
    leak_count = sum(1 for s in sections if s["memory_leaks"])

    template = Template(_HTML_TEMPLATE)
    html = template.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        model=MODEL,
        patches_fetched=result.get("patches_fetched") or header["patches_fetched"],
        series_count=result.get("series_count") or header["series_count"],
        api_calls=len(result.get("tools_used", [])),
        iterations=result.get("iterations", 0),
        sections=sections,
        subsystems=subsystems,
        flagged_count=flagged_count,
        leak_count=leak_count,
        raw_digest=digest_text,
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
