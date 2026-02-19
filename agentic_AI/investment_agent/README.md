# Investment Agent

An AI-powered stock investment agent that analyzes ticker symbols using Claude claude-sonnet-4-6 with tool-use to gather technical and fundamental data via yfinance, producing a polished HTML report with BUY/SELL/HOLD recommendations.

## Features

- **Agentic analysis loop**: Claude autonomously calls tools to gather price history, technical indicators, fundamentals, company info, news, and analyst recommendations
- **Technical analysis**: RSI, MACD, Bollinger Bands, SMA/EMA, volume trends
- **Fundamental analysis**: P/E ratio, EPS growth, debt-to-equity, revenue, profit margins
- **HTML report**: Color-coded recommendations, per-ticker cards with full reasoning
- **Rich CLI progress**: Live status display while analyzing each ticker

## Setup

```bash
# Clone and enter directory
cd investment_agent

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Usage

```bash
python3 main.py AAPL MSFT TSLA NVDA
```

This will:
1. Analyze each ticker using the Claude agent
2. Display live progress in the terminal
3. Generate `investment_report_YYYYMMDD.html` in the current directory

## Sample Output

```
Analyzing AAPL...
  ✓ Price history fetched
  ✓ Technical indicators calculated
  ✓ Fundamentals retrieved
  ✓ Company info loaded
  ✓ News headlines gathered
  ✓ Analyst recommendations retrieved
  → RECOMMENDATION: BUY | Confidence: High | Target: $215

Report saved: investment_report_20260217.html
```

## Project Structure

```
investment_agent/
├── main.py                   # Entry point
├── agents/
│   ├── orchestrator.py       # Agentic loop with Claude
│   └── tools.py              # Tool schemas + implementations
├── data/
│   └── fetcher.py            # yfinance wrapper
├── analysis/
│   ├── technical.py          # RSI, MACD, Bollinger Bands, MAs
│   └── fundamental.py        # Fundamental scoring
├── report/
│   └── generator.py          # HTML report generation
├── config.py                 # Model name, defaults
└── requirements.txt
```

## Disclaimer

This tool is for educational and informational purposes only. It does not constitute financial advice. Always consult a qualified financial advisor before making investment decisions.
