import json
import markdown as md
from datetime import date
from jinja2 import Template

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Investment Analysis Report — {{ report_date }}</title>
<style>
  :root {
    --buy-color: #16a34a;
    --buy-bg: #dcfce7;
    --sell-color: #dc2626;
    --sell-bg: #fee2e2;
    --hold-color: #d97706;
    --hold-bg: #fef3c7;
    --neutral: #6b7280;
    --border: #e5e7eb;
    --card-bg: #ffffff;
    --page-bg: #f9fafb;
    --text: #111827;
    --muted: #6b7280;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--font);
    background: var(--page-bg);
    color: var(--text);
    padding: 2rem 1rem;
    line-height: 1.6;
  }

  .container { max-width: 1100px; margin: 0 auto; }

  /* Header */
  .report-header {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: white;
    border-radius: 12px;
    padding: 2rem;
    margin-bottom: 2rem;
  }
  .report-header h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: 0.5rem; }
  .report-header .meta { opacity: 0.85; font-size: 0.9rem; }
  .disclaimer {
    background: #fef9c3;
    border: 1px solid #fde047;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    font-size: 0.8rem;
    color: #713f12;
    margin-top: 1rem;
  }

  /* Summary table */
  .summary-section { margin-bottom: 2.5rem; }
  .section-title {
    font-size: 1.2rem;
    font-weight: 700;
    margin-bottom: 1rem;
    color: var(--text);
  }
  .summary-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  .summary-table th {
    background: #f3f4f6;
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
  }
  .summary-table td { padding: 0.9rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.95rem; }
  .summary-table tr:last-child td { border-bottom: none; }
  .summary-table tr:hover { background: #f9fafb; }

  /* Badges */
  .badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-weight: 700;
    font-size: 0.8rem;
    letter-spacing: 0.03em;
  }
  .badge-buy { background: var(--buy-bg); color: var(--buy-color); }
  .badge-sell { background: var(--sell-bg); color: var(--sell-color); }
  .badge-hold { background: var(--hold-bg); color: var(--hold-color); }
  .badge-high { background: #dcfce7; color: #15803d; }
  .badge-medium { background: #fef3c7; color: #b45309; }
  .badge-low { background: #fee2e2; color: #b91c1c; }

  /* Ticker cards */
  .ticker-card {
    background: var(--card-bg);
    border-radius: 12px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.10);
    margin-bottom: 2rem;
    overflow: hidden;
  }
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.2rem 1.5rem;
    border-bottom: 1px solid var(--border);
  }
  .card-header-left h2 { font-size: 1.4rem; font-weight: 800; }
  .card-header-left .company-name { color: var(--muted); font-size: 0.9rem; }
  .card-header-right { text-align: right; }
  .card-price { font-size: 1.5rem; font-weight: 700; }
  .card-change { font-size: 0.85rem; }
  .positive { color: var(--buy-color); }
  .negative { color: var(--sell-color); }

  .card-body { padding: 1.5rem; }

  /* Recommendation box */
  .rec-box {
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    border-left: 5px solid;
  }
  .rec-box.buy { background: var(--buy-bg); border-color: var(--buy-color); }
  .rec-box.sell { background: var(--sell-bg); border-color: var(--sell-color); }
  .rec-box.hold { background: var(--hold-bg); border-color: var(--hold-color); }
  .rec-box h3 { font-size: 1rem; font-weight: 700; margin-bottom: 0.25rem; }

  /* Two-column layout */
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
  @media (max-width: 700px) { .two-col { grid-template-columns: 1fr; } }

  /* Data tables inside cards */
  .data-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  .data-table th { text-align: left; font-weight: 600; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); }
  .data-table td { padding: 0.45rem 0.5rem; border-bottom: 1px solid #f3f4f6; }
  .data-table tr:last-child td { border-bottom: none; }
  .flag-bullish { color: var(--buy-color); font-weight: 600; }
  .flag-bearish { color: var(--sell-color); font-weight: 600; }
  .flag-neutral { color: var(--neutral); }
  .flag-unavailable { color: #9ca3af; font-style: italic; }

  /* Technical signals */
  .signal-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 0.75rem; margin-bottom: 1.5rem; }
  .signal-card {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.75rem;
    text-align: center;
  }
  .signal-card .label { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.25rem; }
  .signal-card .value { font-size: 1.1rem; font-weight: 700; }
  .signal-card .sig { font-size: 0.75rem; font-weight: 600; margin-top: 0.2rem; }
  .sig-buy { color: var(--buy-color); }
  .sig-sell { color: var(--sell-color); }
  .sig-neutral { color: var(--neutral); }

  /* Reasoning text */
  .reasoning-section h4 { font-weight: 700; margin-bottom: 0.75rem; }
  .reasoning-text { font-size: 0.9rem; color: #374151; line-height: 1.7; }
  .reasoning-text h1, .reasoning-text h2, .reasoning-text h3 { margin: 1rem 0 0.5rem; font-size: 1rem; color: var(--text); }
  .reasoning-text h1 { font-size: 1.1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }
  .reasoning-text p { margin-bottom: 0.75rem; }
  .reasoning-text ul, .reasoning-text ol { padding-left: 1.5rem; margin-bottom: 0.75rem; }
  .reasoning-text li { margin-bottom: 0.25rem; }
  .reasoning-text strong { font-weight: 700; color: #111827; }
  .reasoning-text em { font-style: italic; }
  .reasoning-text hr { border: none; border-top: 1px solid var(--border); margin: 1rem 0; }
  .reasoning-text blockquote { border-left: 3px solid #d1d5db; padding-left: 1rem; color: var(--muted); margin: 0.75rem 0; font-style: italic; }
  .reasoning-text table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 0.75rem 0; }
  .reasoning-text table th { background: #f3f4f6; padding: 0.4rem 0.75rem; text-align: left; font-weight: 600; border: 1px solid var(--border); }
  .reasoning-text table td { padding: 0.4rem 0.75rem; border: 1px solid var(--border); }
  .reasoning-text table tr:nth-child(even) { background: #f9fafb; }
  .reasoning-text code { background: #f3f4f6; padding: 0.1rem 0.3rem; border-radius: 3px; font-family: monospace; font-size: 0.85em; }

  /* News */
  .news-list { list-style: none; }
  .news-list li { padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.875rem; }
  .news-list li:last-child { border-bottom: none; }
  .news-title { font-weight: 500; }
  .news-meta { color: var(--muted); font-size: 0.78rem; margin-top: 0.1rem; }

  /* Subsection headers */
  .subsection-title { font-size: 0.875rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }

  /* Footer */
  .report-footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="report-header">
    <h1>AI Investment Analysis Report</h1>
    <div class="meta">Generated: {{ report_date }} &nbsp;|&nbsp; Model: claude-sonnet-4-6 &nbsp;|&nbsp; Tickers: {{ tickers|join(', ') }}</div>
    <div class="disclaimer">
      <strong>Disclaimer:</strong> This report is generated by an AI system for informational and educational purposes only. It does not constitute financial advice, investment recommendations, or solicitation to buy or sell securities. Past performance is not indicative of future results. Always consult a qualified financial advisor before making investment decisions.
    </div>
  </div>

  <!-- Summary Table -->
  <div class="summary-section">
    <div class="section-title">Summary</div>
    <table class="summary-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Company</th>
          <th>Current Price</th>
          <th>Period Change</th>
          <th>Recommendation</th>
          <th>Confidence</th>
          <th>Target</th>
        </tr>
      </thead>
      <tbody>
        {% for r in results %}
        <tr>
          <td><strong>{{ r.ticker }}</strong></td>
          <td>{{ r.company_name }}</td>
          <td>${{ r.current_price }}</td>
          <td class="{{ 'positive' if r.period_change >= 0 else 'negative' }}">
            {{ '+' if r.period_change >= 0 else '' }}{{ r.period_change }}%
          </td>
          <td><span class="badge badge-{{ r.recommendation|lower }}">{{ r.recommendation }}</span></td>
          <td><span class="badge badge-{{ r.confidence|lower }}">{{ r.confidence }}</span></td>
          <td>{{ r.target_price }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Per-ticker cards -->
  {% for r in results %}
  <div class="ticker-card" id="{{ r.ticker }}">
    <div class="card-header">
      <div class="card-header-left">
        <h2>{{ r.ticker }}</h2>
        <div class="company-name">{{ r.company_name }} &nbsp;|&nbsp; {{ r.sector }} / {{ r.industry }}</div>
      </div>
      <div class="card-header-right">
        <div class="card-price">${{ r.current_price }}</div>
        <div class="card-change {{ 'positive' if r.period_change >= 0 else 'negative' }}">
          {{ '+' if r.period_change >= 0 else '' }}{{ r.period_change }}% (6mo)
        </div>
      </div>
    </div>

    <div class="card-body">

      <!-- Recommendation box -->
      <div class="rec-box {{ r.recommendation|lower }}">
        <h3>{{ r.recommendation }} &nbsp;|&nbsp; Confidence: {{ r.confidence }} &nbsp;|&nbsp; Target: {{ r.target_price }}</h3>
      </div>

      <!-- Technical signals -->
      {% if r.technical %}
      <div class="subsection-title">Technical Signals</div>
      <div class="signal-grid">
        {% if r.technical.rsi %}
        <div class="signal-card">
          <div class="label">RSI (14)</div>
          <div class="value">{{ r.technical.rsi.rsi }}</div>
          <div class="sig sig-{{ r.technical.rsi.signal|lower }}">{{ r.technical.rsi.signal }} — {{ r.technical.rsi.condition }}</div>
        </div>
        {% endif %}
        {% if r.technical.macd %}
        <div class="signal-card">
          <div class="label">MACD</div>
          <div class="value">{{ r.technical.macd.histogram }}</div>
          <div class="sig sig-{{ r.technical.macd.signal|lower }}">{{ r.technical.macd.signal }} — {{ r.technical.macd.crossover }}</div>
        </div>
        {% endif %}
        {% if r.technical.bollinger_bands %}
        <div class="signal-card">
          <div class="label">Bollinger Position</div>
          <div class="value">{{ r.technical.bollinger_bands.price_position_pct }}%</div>
          <div class="sig sig-{{ r.technical.bollinger_bands.signal|lower }}">{{ r.technical.bollinger_bands.signal }}</div>
        </div>
        {% endif %}
        {% if r.technical.moving_averages %}
        <div class="signal-card">
          <div class="label">Moving Averages</div>
          <div class="value">{{ r.technical.moving_averages.trend_strength }}</div>
          <div class="sig sig-{{ r.technical.moving_averages.signal|lower }}">{{ r.technical.moving_averages.signal }}</div>
        </div>
        {% endif %}
        {% if r.technical.volume_trend %}
        <div class="signal-card">
          <div class="label">Volume Trend</div>
          <div class="value">{{ r.technical.volume_trend.volume_ratio }}x</div>
          <div class="sig sig-{{ r.technical.volume_trend.signal }}">{{ r.technical.volume_trend.trend }}</div>
        </div>
        {% endif %}
        {% if r.technical.aggregate_signal %}
        <div class="signal-card">
          <div class="label">Aggregate Signal</div>
          <div class="value">{{ r.technical.aggregate_signal.buy_signals }}B / {{ r.technical.aggregate_signal.sell_signals }}S</div>
          <div class="sig sig-{{ r.technical.aggregate_signal.overall|lower }}">{{ r.technical.aggregate_signal.overall }}</div>
        </div>
        {% endif %}
      </div>
      {% endif %}

      <div class="two-col">
        <!-- Fundamentals -->
        {% if r.fundamental_analysis %}
        <div>
          <div class="subsection-title">Fundamental Metrics</div>
          <table class="data-table">
            <thead><tr><th>Metric</th><th>Value</th><th>Signal</th><th>Note</th></tr></thead>
            <tbody>
              {% for metric_name, metric in r.fundamental_analysis.metrics.items() %}
              <tr>
                <td>{{ metric_name|replace('_', ' ')|title }}</td>
                <td>
                  {% if metric.value is not none %}
                    {% if metric_name in ['gross_margins', 'profit_margins', 'operating_margins', 'return_on_equity', 'return_on_assets', 'revenue_growth'] %}
                      {{ metric.value }}%
                    {% else %}
                      {{ metric.value }}
                    {% endif %}
                  {% else %}
                    —
                  {% endif %}
                </td>
                <td class="flag-{{ metric.flag }}">{{ metric.flag|upper }}</td>
                <td>{{ metric.note }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          <div style="margin-top:0.75rem; font-size:0.82rem; color:var(--muted);">
            Overall: <strong>{{ r.fundamental_analysis.overall|upper }}</strong> — {{ r.fundamental_analysis.summary }}
          </div>
        </div>
        {% endif %}

        <!-- News & Analysts -->
        <div>
          {% if r.analyst %}
          <div class="subsection-title">Analyst Consensus</div>
          <table class="data-table" style="margin-bottom:1rem;">
            <tbody>
              <tr><td>Consensus</td><td><strong>{{ r.analyst.consensus }}</strong></td></tr>
              <tr><td>Strong Buy / Buy</td><td>{{ r.analyst.bullish }}</td></tr>
              <tr><td>Hold</td><td>{{ r.analyst.neutral }}</td></tr>
              <tr><td>Sell / Strong Sell</td><td>{{ r.analyst.bearish }}</td></tr>
              <tr><td>Total Analysts</td><td>{{ r.analyst.total_analysts }}</td></tr>
            </tbody>
          </table>
          {% endif %}

          {% if r.news %}
          <div class="subsection-title">Recent News</div>
          <ul class="news-list">
            {% for item in r.news[:6] %}
            <li>
              <div class="news-title">
                {% if item.link %}<a href="{{ item.link }}" target="_blank" rel="noopener">{{ item.title }}</a>{% else %}{{ item.title }}{% endif %}
              </div>
              <div class="news-meta">{{ item.publisher }} &nbsp;|&nbsp; {{ item.published_at }}</div>
            </li>
            {% endfor %}
          </ul>
          {% endif %}
        </div>
      </div>

      <!-- AI Reasoning -->
      <div class="reasoning-section">
        <div class="subsection-title">AI Analysis &amp; Reasoning</div>
        <div class="reasoning-text">{{ r.reasoning | safe }}</div>
      </div>

    </div>
  </div>
  {% endfor %}

  <div class="report-footer">
    Generated by Investment Agent &nbsp;|&nbsp; Powered by Claude claude-sonnet-4-6 &amp; yfinance &nbsp;|&nbsp; {{ report_date }}
  </div>

</div>
</body>
</html>
"""


def _safe_json_load(json_str: str) -> dict:
    try:
        return json.loads(json_str)
    except Exception:
        return {}


def _extract_snapshot_data(data_snapshot: dict) -> tuple:
    """Extract structured data from the agent's data_snapshot for the report."""
    technical = {}
    fundamental_analysis = None
    fundamental_raw = {}
    company = {}
    news_items = []
    analyst = {}
    price_data = {}

    for tool_name, json_str in data_snapshot.items():
        d = _safe_json_load(json_str) if isinstance(json_str, str) else json_str

        if tool_name == "get_price_history":
            price_data = d
        elif tool_name == "calculate_technical_indicators":
            technical = d
        elif tool_name == "get_fundamental_data":
            fundamental_raw = d.get("raw_data", {})
            fundamental_analysis = d.get("analysis", None)
        elif tool_name == "get_company_info":
            company = d
        elif tool_name == "get_recent_news":
            news_items = d.get("news", [])
        elif tool_name == "get_analyst_recommendations":
            analyst = d

    return technical, fundamental_analysis, fundamental_raw, company, news_items, analyst, price_data


def generate_html_report(results: list, output_path: str) -> str:
    """
    Render results list to HTML report.
    Each result is a dict from orchestrator.analyze_stock().
    Returns the output path.
    """
    report_date = date.today().strftime("%Y-%m-%d")
    tickers = [r["ticker"] for r in results]

    rendered_results = []
    for r in results:
        technical, fundamental_analysis, fundamental_raw, company, news_items, analyst, price_data = \
            _extract_snapshot_data(r.get("data_snapshot", {}))

        current_price = price_data.get("current_price", "N/A")
        period_change = price_data.get("period_change_pct", 0.0)
        company_name = company.get("name", r["ticker"])
        sector = company.get("sector", "Unknown")
        industry = company.get("industry", "Unknown")

        raw_reasoning = r.get("reasoning", "No reasoning provided.")
        rendered_reasoning = md.markdown(
            raw_reasoning,
            extensions=["tables", "nl2br", "sane_lists"],
        )

        rendered_results.append({
            "ticker": r["ticker"],
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "current_price": current_price,
            "period_change": period_change,
            "recommendation": r.get("recommendation", "HOLD"),
            "confidence": r.get("confidence", "Medium"),
            "target_price": r.get("target_price", "N/A"),
            "reasoning": rendered_reasoning,
            "technical": technical,
            "fundamental_analysis": fundamental_analysis,
            "analyst": analyst if analyst and "error" not in analyst else None,
            "news": news_items,
        })

    template = Template(HTML_TEMPLATE)
    html_content = template.render(
        report_date=report_date,
        tickers=tickers,
        results=rendered_results,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path
