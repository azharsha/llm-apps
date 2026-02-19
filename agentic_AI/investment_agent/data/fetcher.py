import yfinance as yf
import pandas as pd
from datetime import datetime
from config import DEFAULT_PERIOD, DEFAULT_INTERVAL


def fetch_price_history(ticker: str, period: str = DEFAULT_PERIOD, interval: str = DEFAULT_INTERVAL) -> dict:
    """Fetch OHLCV price history and summary statistics."""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval)

    if df.empty:
        return {"error": f"No price data found for {ticker}"}

    current_price = float(df["Close"].iloc[-1])
    start_price = float(df["Close"].iloc[0])
    price_change_pct = ((current_price - start_price) / start_price) * 100

    high_52w = float(df["High"].max())
    low_52w = float(df["Low"].min())

    avg_volume = float(df["Volume"].mean())
    latest_volume = float(df["Volume"].iloc[-1])

    # Build recent price table (last 10 days)
    recent = df.tail(10)[["Open", "High", "Low", "Close", "Volume"]].copy()
    recent.index = recent.index.strftime("%Y-%m-%d")
    recent_records = recent.round(2).to_dict(orient="index")

    return {
        "ticker": ticker,
        "current_price": round(current_price, 2),
        "period_start_price": round(start_price, 2),
        "period_change_pct": round(price_change_pct, 2),
        "52w_high": round(high_52w, 2),
        "52w_low": round(low_52w, 2),
        "avg_volume": int(avg_volume),
        "latest_volume": int(latest_volume),
        "data_points": len(df),
        "period": period,
        "interval": interval,
        "recent_prices": recent_records,
    }


def fetch_fundamentals(ticker: str) -> dict:
    """Fetch fundamental financial data."""
    stock = yf.Ticker(ticker)
    info = stock.info

    def safe_get(key, default=None):
        val = info.get(key, default)
        if val is None:
            return default
        try:
            if isinstance(val, float) and (val != val):  # NaN check
                return default
            return val
        except Exception:
            return default

    return {
        "ticker": ticker,
        "market_cap": safe_get("marketCap"),
        "pe_ratio": safe_get("trailingPE"),
        "forward_pe": safe_get("forwardPE"),
        "eps": safe_get("trailingEps"),
        "eps_forward": safe_get("forwardEps"),
        "revenue": safe_get("totalRevenue"),
        "revenue_growth": safe_get("revenueGrowth"),
        "gross_margins": safe_get("grossMargins"),
        "profit_margins": safe_get("profitMargins"),
        "operating_margins": safe_get("operatingMargins"),
        "debt_to_equity": safe_get("debtToEquity"),
        "current_ratio": safe_get("currentRatio"),
        "return_on_equity": safe_get("returnOnEquity"),
        "return_on_assets": safe_get("returnOnAssets"),
        "book_value": safe_get("bookValue"),
        "price_to_book": safe_get("priceToBook"),
        "dividend_yield": safe_get("dividendYield"),
        "beta": safe_get("beta"),
        "52_week_change": safe_get("52WeekChange"),
        "shares_outstanding": safe_get("sharesOutstanding"),
        "float_shares": safe_get("floatShares"),
        "short_ratio": safe_get("shortRatio"),
        "peg_ratio": safe_get("pegRatio"),
        "enterprise_value": safe_get("enterpriseValue"),
        "ev_to_revenue": safe_get("enterpriseToRevenue"),
        "ev_to_ebitda": safe_get("enterpriseToEbitda"),
    }


def fetch_company_info(ticker: str) -> dict:
    """Fetch company sector, industry, description, and employee count."""
    stock = yf.Ticker(ticker)
    info = stock.info

    def safe_get(key, default=None):
        return info.get(key, default)

    description = safe_get("longBusinessSummary", "")
    # Truncate long descriptions
    if description and len(description) > 800:
        description = description[:800] + "..."

    return {
        "ticker": ticker,
        "name": safe_get("longName") or safe_get("shortName", ticker),
        "sector": safe_get("sector", "Unknown"),
        "industry": safe_get("industry", "Unknown"),
        "country": safe_get("country", "Unknown"),
        "employees": safe_get("fullTimeEmployees"),
        "website": safe_get("website"),
        "description": description,
        "exchange": safe_get("exchange"),
        "currency": safe_get("currency", "USD"),
    }


def fetch_news(ticker: str, count: int = 10) -> dict:
    """Fetch latest news headlines for the ticker."""
    stock = yf.Ticker(ticker)

    try:
        news_items = stock.news or []
    except Exception:
        news_items = []

    formatted = []
    for item in news_items[:count]:
        formatted.append({
            "title": item.get("title", ""),
            "publisher": item.get("publisher", ""),
            "link": item.get("link", ""),
            "published_at": datetime.fromtimestamp(item.get("providerPublishTime", 0)).strftime("%Y-%m-%d %H:%M")
            if item.get("providerPublishTime")
            else "",
        })

    return {
        "ticker": ticker,
        "news_count": len(formatted),
        "news": formatted,
    }


def fetch_analyst_recommendations(ticker: str) -> dict:
    """Fetch latest analyst buy/sell/hold ratings."""
    stock = yf.Ticker(ticker)

    try:
        recs = stock.recommendations
    except Exception:
        recs = None

    if recs is None or recs.empty:
        # Try upgrades_downgrades as fallback
        try:
            upgrades = stock.upgrades_downgrades
            if upgrades is not None and not upgrades.empty:
                recent = upgrades.head(10)
                recent.index = recent.index.strftime("%Y-%m-%d")
                return {
                    "ticker": ticker,
                    "source": "upgrades_downgrades",
                    "recent_actions": recent.to_dict(orient="index"),
                }
        except Exception:
            pass
        return {"ticker": ticker, "error": "No analyst recommendations available"}

    # Summarize recent recommendations
    try:
        recent = recs.tail(4)  # last 4 periods
        summary = {}
        for col in ["strongBuy", "buy", "hold", "sell", "strongSell"]:
            if col in recent.columns:
                summary[col] = int(recent[col].sum())

        latest_period = recent.index[-1]
        if hasattr(latest_period, "strftime"):
            period_str = latest_period.strftime("%Y-%m-%d")
        else:
            period_str = str(latest_period)

        total = sum(summary.values())
        bullish = summary.get("strongBuy", 0) + summary.get("buy", 0)
        bearish = summary.get("sell", 0) + summary.get("strongSell", 0)
        neutral = summary.get("hold", 0)

        consensus = "HOLD"
        if total > 0:
            bull_pct = bullish / total
            bear_pct = bearish / total
            if bull_pct > 0.5:
                consensus = "BUY"
            elif bear_pct > 0.4:
                consensus = "SELL"

        return {
            "ticker": ticker,
            "latest_period": period_str,
            "summary": summary,
            "total_analysts": total,
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "consensus": consensus,
        }
    except Exception as e:
        return {"ticker": ticker, "error": f"Failed to parse recommendations: {e}"}
