import numpy as np
import pandas as pd
from typing import Union


def _to_series(prices: Union[list, pd.Series]) -> pd.Series:
    if isinstance(prices, pd.Series):
        return prices.dropna().reset_index(drop=True)
    return pd.Series(prices, dtype=float).dropna().reset_index(drop=True)


def calculate_rsi(prices: Union[list, pd.Series], period: int = 14) -> dict:
    """Calculate RSI and trend classification."""
    s = _to_series(prices)
    if len(s) < period + 1:
        return {"error": f"Need at least {period + 1} data points for RSI"}

    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    current_rsi = float(rsi.iloc[-1])
    prev_rsi = float(rsi.iloc[-2]) if len(rsi) >= 2 else current_rsi

    if current_rsi >= 70:
        condition = "overbought"
    elif current_rsi <= 30:
        condition = "oversold"
    elif current_rsi >= 55:
        condition = "bullish"
    elif current_rsi <= 45:
        condition = "bearish"
    else:
        condition = "neutral"

    trend = "rising" if current_rsi > prev_rsi else "falling"

    return {
        "rsi": round(current_rsi, 2),
        "previous_rsi": round(prev_rsi, 2),
        "condition": condition,
        "trend": trend,
        "signal": "SELL" if current_rsi >= 70 else ("BUY" if current_rsi <= 30 else "NEUTRAL"),
    }


def calculate_macd(prices: Union[list, pd.Series], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Calculate MACD line, signal line, histogram, and crossover signal."""
    s = _to_series(prices)
    if len(s) < slow + signal:
        return {"error": f"Need at least {slow + signal} data points for MACD"}

    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    current_macd = float(macd_line.iloc[-1])
    current_signal = float(signal_line.iloc[-1])
    current_hist = float(histogram.iloc[-1])
    prev_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 else current_hist
    prev_macd = float(macd_line.iloc[-2]) if len(macd_line) >= 2 else current_macd
    prev_signal_val = float(signal_line.iloc[-2]) if len(signal_line) >= 2 else current_signal

    # Detect crossover
    crossover = "none"
    if prev_macd <= prev_signal_val and current_macd > current_signal:
        crossover = "bullish_crossover"
    elif prev_macd >= prev_signal_val and current_macd < current_signal:
        crossover = "bearish_crossover"

    momentum = "increasing" if current_hist > prev_hist else "decreasing"
    bullish = current_macd > current_signal and current_hist > 0

    return {
        "macd_line": round(current_macd, 4),
        "signal_line": round(current_signal, 4),
        "histogram": round(current_hist, 4),
        "crossover": crossover,
        "momentum": momentum,
        "bullish": bullish,
        "signal": "BUY" if crossover == "bullish_crossover" else ("SELL" if crossover == "bearish_crossover" else ("BUY" if bullish else "SELL")),
    }


def calculate_bollinger_bands(prices: Union[list, pd.Series], period: int = 20, std_dev: float = 2.0) -> dict:
    """Calculate Bollinger Bands and price position."""
    s = _to_series(prices)
    if len(s) < period:
        return {"error": f"Need at least {period} data points for Bollinger Bands"}

    middle = s.rolling(window=period).mean()
    std = s.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    current_price = float(s.iloc[-1])
    current_upper = float(upper.iloc[-1])
    current_middle = float(middle.iloc[-1])
    current_lower = float(lower.iloc[-1])

    band_width = current_upper - current_lower
    if band_width > 0:
        price_position_pct = ((current_price - current_lower) / band_width) * 100
    else:
        price_position_pct = 50.0

    if current_price >= current_upper:
        position = "above_upper_band"
        signal = "SELL"
    elif current_price <= current_lower:
        position = "below_lower_band"
        signal = "BUY"
    elif price_position_pct > 80:
        position = "near_upper_band"
        signal = "SELL"
    elif price_position_pct < 20:
        position = "near_lower_band"
        signal = "BUY"
    else:
        position = "within_bands"
        signal = "NEUTRAL"

    squeeze = band_width / current_middle < 0.05 if current_middle > 0 else False

    return {
        "upper_band": round(current_upper, 2),
        "middle_band": round(current_middle, 2),
        "lower_band": round(current_lower, 2),
        "current_price": round(current_price, 2),
        "price_position_pct": round(price_position_pct, 1),
        "position": position,
        "band_width": round(band_width, 2),
        "squeeze": squeeze,
        "signal": signal,
    }


def calculate_moving_averages(prices: Union[list, pd.Series]) -> dict:
    """Calculate SMA20, SMA50, SMA200 and price relationship to each."""
    s = _to_series(prices)
    current_price = float(s.iloc[-1])

    result = {"current_price": round(current_price, 2)}

    for period in [20, 50, 200]:
        key = f"sma{period}"
        if len(s) >= period:
            sma_val = float(s.rolling(window=period).mean().iloc[-1])
            diff_pct = ((current_price - sma_val) / sma_val) * 100
            result[key] = round(sma_val, 2)
            result[f"{key}_diff_pct"] = round(diff_pct, 2)
            result[f"price_above_{key}"] = current_price > sma_val
        else:
            result[key] = None
            result[f"{key}_diff_pct"] = None
            result[f"price_above_{key}"] = None

    # Golden/death cross detection (SMA50 vs SMA200)
    result["golden_cross"] = False
    result["death_cross"] = False
    if len(s) >= 200:
        sma50_series = s.rolling(window=50).mean()
        sma200_series = s.rolling(window=200).mean()
        if len(sma50_series) >= 2 and len(sma200_series) >= 2:
            prev_50 = float(sma50_series.iloc[-2])
            prev_200 = float(sma200_series.iloc[-2])
            curr_50 = float(sma50_series.iloc[-1])
            curr_200 = float(sma200_series.iloc[-1])
            if prev_50 <= prev_200 and curr_50 > curr_200:
                result["golden_cross"] = True
            elif prev_50 >= prev_200 and curr_50 < curr_200:
                result["death_cross"] = True

    # Trend signal based on MAs
    bullish_signals = sum([
        result.get("price_above_sma20") or False,
        result.get("price_above_sma50") or False,
        result.get("price_above_sma200") or False,
    ])
    result["signal"] = "BUY" if bullish_signals >= 2 else "SELL"
    result["trend_strength"] = f"{bullish_signals}/3 MAs bullish"

    return result


def calculate_volume_trend(df: pd.DataFrame) -> dict:
    """Calculate volume statistics and trend."""
    if "Volume" not in df.columns:
        return {"error": "Volume column not found in dataframe"}

    vol = df["Volume"].dropna()
    if vol.empty:
        return {"error": "No volume data available"}

    avg_volume = float(vol.mean())
    current_volume = float(vol.iloc[-1])
    vol_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

    # 5-day trend
    recent_5 = vol.tail(5)
    older_5 = vol.iloc[-10:-5] if len(vol) >= 10 else vol

    recent_avg = float(recent_5.mean())
    older_avg = float(older_5.mean()) if not older_5.empty else recent_avg
    vol_trend_pct = ((recent_avg - older_avg) / older_avg) * 100 if older_avg > 0 else 0

    trend = "increasing" if vol_trend_pct > 5 else ("decreasing" if vol_trend_pct < -5 else "stable")
    signal = "bullish" if vol_trend_pct > 10 else ("bearish" if vol_trend_pct < -10 else "neutral")

    return {
        "avg_volume": int(avg_volume),
        "current_volume": int(current_volume),
        "volume_ratio": round(vol_ratio, 2),
        "5day_avg_volume": int(recent_avg),
        "volume_trend_pct": round(vol_trend_pct, 1),
        "trend": trend,
        "signal": signal,
        "high_volume_day": vol_ratio > 1.5,
    }
