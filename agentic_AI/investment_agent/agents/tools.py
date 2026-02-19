import json
import yfinance as yf
from data.fetcher import (
    fetch_price_history,
    fetch_fundamentals,
    fetch_company_info,
    fetch_news,
    fetch_analyst_recommendations,
)
from analysis.technical import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_moving_averages,
    calculate_volume_trend,
)
from analysis.fundamental import score_fundamentals
from config import DEFAULT_PERIOD, DEFAULT_INTERVAL


TOOL_SCHEMAS = [
    {
        "name": "get_price_history",
        "description": (
            "Fetch historical OHLCV price data for a stock ticker. Returns current price, "
            "period change %, 52-week high/low, volume stats, and recent daily prices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                },
                "period": {
                    "type": "string",
                    "description": "Data period: 1mo, 3mo, 6mo, 1y, 2y, 5y (default: 6mo)",
                    "default": DEFAULT_PERIOD,
                },
                "interval": {
                    "type": "string",
                    "description": "Data interval: 1d, 1wk, 1mo (default: 1d)",
                    "default": DEFAULT_INTERVAL,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "calculate_technical_indicators",
        "description": (
            "Calculate technical indicators for a stock: RSI (overbought/oversold), "
            "MACD (momentum and crossovers), Bollinger Bands (price position), "
            "Moving Averages (SMA20/50/200), and Volume trend analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
                "period": {
                    "type": "string",
                    "description": "Data period for calculation (default: 6mo)",
                    "default": DEFAULT_PERIOD,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fundamental_data",
        "description": (
            "Fetch and score fundamental financial data: P/E ratio, EPS, revenue growth, "
            "profit margins, debt-to-equity, ROE, PEG ratio, current ratio, market cap. "
            "Includes bullish/bearish flags per metric and overall fundamental score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_info",
        "description": (
            "Fetch company profile: sector, industry, country, employee count, "
            "website, business description, and exchange listing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_recent_news",
        "description": (
            "Fetch the latest news headlines for a stock ticker from Yahoo Finance. "
            "Returns up to 10 recent articles with title, publisher, and publication date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of news items to fetch (default: 10, max: 10)",
                    "default": 10,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_analyst_recommendations",
        "description": (
            "Fetch analyst buy/sell/hold ratings and consensus recommendation. "
            "Returns counts of strongBuy, buy, hold, sell, strongSell from recent quarters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                },
            },
            "required": ["ticker"],
        },
    },
]


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch a tool call and return JSON-encoded result."""
    try:
        result = _execute_tool(tool_name, tool_input)
    except Exception as e:
        result = {"error": f"Tool execution failed: {str(e)}", "tool": tool_name}
    return json.dumps(result, default=str)


def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    ticker = tool_input.get("ticker", "").upper().strip()

    if tool_name == "get_price_history":
        period = tool_input.get("period", DEFAULT_PERIOD)
        interval = tool_input.get("interval", DEFAULT_INTERVAL)
        return fetch_price_history(ticker, period, interval)

    elif tool_name == "calculate_technical_indicators":
        period = tool_input.get("period", DEFAULT_PERIOD)
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=DEFAULT_INTERVAL)

        if df.empty:
            return {"error": f"No data available for {ticker}"}

        closes = df["Close"]
        indicators = {
            "ticker": ticker,
            "data_points": len(df),
            "rsi": calculate_rsi(closes),
            "macd": calculate_macd(closes),
            "bollinger_bands": calculate_bollinger_bands(closes),
            "moving_averages": calculate_moving_averages(closes),
            "volume_trend": calculate_volume_trend(df),
        }

        # Aggregate signals
        signals = [
            indicators["rsi"].get("signal", "NEUTRAL"),
            indicators["macd"].get("signal", "NEUTRAL"),
            indicators["bollinger_bands"].get("signal", "NEUTRAL"),
            indicators["moving_averages"].get("signal", "NEUTRAL"),
        ]
        buy_count = signals.count("BUY")
        sell_count = signals.count("SELL")

        indicators["aggregate_signal"] = {
            "buy_signals": buy_count,
            "sell_signals": sell_count,
            "neutral_signals": len(signals) - buy_count - sell_count,
            "overall": "BUY" if buy_count > sell_count else ("SELL" if sell_count > buy_count else "NEUTRAL"),
        }
        return indicators

    elif tool_name == "get_fundamental_data":
        raw = fetch_fundamentals(ticker)
        scored = score_fundamentals(raw)
        return {
            "ticker": ticker,
            "raw_data": raw,
            "analysis": scored,
        }

    elif tool_name == "get_company_info":
        return fetch_company_info(ticker)

    elif tool_name == "get_recent_news":
        count = tool_input.get("count", 10)
        return fetch_news(ticker, count)

    elif tool_name == "get_analyst_recommendations":
        return fetch_analyst_recommendations(ticker)

    else:
        return {"error": f"Unknown tool: {tool_name}"}
