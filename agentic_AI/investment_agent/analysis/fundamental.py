from typing import Optional


def _flag(value: Optional[float], bullish_condition: bool, bearish_condition: bool) -> str:
    if value is None:
        return "unavailable"
    if bullish_condition:
        return "bullish"
    if bearish_condition:
        return "bearish"
    return "neutral"


def score_fundamentals(data: dict) -> dict:
    """
    Score fundamental metrics and return structured dict with bullish/bearish flags.
    Returns a dict with per-metric analysis and an overall score.
    """
    metrics = {}

    # P/E Ratio
    pe = data.get("pe_ratio")
    forward_pe = data.get("forward_pe")
    metrics["pe_ratio"] = {
        "value": pe,
        "forward_pe": forward_pe,
        "flag": _flag(
            pe,
            bullish_condition=pe is not None and 5 < pe < 25,
            bearish_condition=pe is not None and (pe > 50 or pe < 0),
        ),
        "note": (
            "Reasonable valuation" if pe and 5 < pe < 25
            else "Potentially overvalued" if pe and pe > 50
            else "Negative earnings" if pe and pe < 0
            else "Value territory" if pe and pe <= 5
            else "Data unavailable"
        ),
    }

    # EPS
    eps = data.get("eps")
    eps_forward = data.get("eps_forward")
    eps_growth = None
    if eps and eps_forward and eps != 0:
        eps_growth = ((eps_forward - eps) / abs(eps)) * 100
    metrics["eps"] = {
        "value": eps,
        "forward_eps": eps_forward,
        "growth_pct": round(eps_growth, 1) if eps_growth is not None else None,
        "flag": _flag(
            eps,
            bullish_condition=eps is not None and eps > 0 and (eps_growth is None or eps_growth > 5),
            bearish_condition=eps is not None and eps < 0,
        ),
        "note": f"EPS growth: {eps_growth:.1f}%" if eps_growth else ("Positive earnings" if eps and eps > 0 else "Negative earnings" if eps else "Data unavailable"),
    }

    # Profit Margins
    pm = data.get("profit_margins")
    metrics["profit_margins"] = {
        "value": round(pm * 100, 2) if pm is not None else None,
        "flag": _flag(
            pm,
            bullish_condition=pm is not None and pm > 0.15,
            bearish_condition=pm is not None and pm < 0,
        ),
        "note": (
            "High margin business" if pm and pm > 0.15
            else "Moderate margins" if pm and 0 < pm <= 0.15
            else "Unprofitable" if pm and pm < 0
            else "Data unavailable"
        ),
    }

    # Revenue Growth
    rev_growth = data.get("revenue_growth")
    metrics["revenue_growth"] = {
        "value": round(rev_growth * 100, 2) if rev_growth is not None else None,
        "flag": _flag(
            rev_growth,
            bullish_condition=rev_growth is not None and rev_growth > 0.10,
            bearish_condition=rev_growth is not None and rev_growth < 0,
        ),
        "note": (
            "Strong revenue growth" if rev_growth and rev_growth > 0.10
            else "Modest growth" if rev_growth and 0 < rev_growth <= 0.10
            else "Revenue declining" if rev_growth and rev_growth < 0
            else "Data unavailable"
        ),
    }

    # Debt-to-Equity
    de = data.get("debt_to_equity")
    metrics["debt_to_equity"] = {
        "value": round(de / 100, 2) if de is not None else None,  # yfinance returns as percentage
        "flag": _flag(
            de,
            bullish_condition=de is not None and de < 100,
            bearish_condition=de is not None and de > 200,
        ),
        "note": (
            "Low leverage" if de and de < 100
            else "Moderate leverage" if de and 100 <= de <= 200
            else "High leverage" if de and de > 200
            else "Data unavailable"
        ),
    }

    # Return on Equity
    roe = data.get("return_on_equity")
    metrics["return_on_equity"] = {
        "value": round(roe * 100, 2) if roe is not None else None,
        "flag": _flag(
            roe,
            bullish_condition=roe is not None and roe > 0.15,
            bearish_condition=roe is not None and roe < 0,
        ),
        "note": (
            "Strong ROE" if roe and roe > 0.15
            else "Decent ROE" if roe and 0 < roe <= 0.15
            else "Negative ROE" if roe and roe < 0
            else "Data unavailable"
        ),
    }

    # PEG Ratio
    peg = data.get("peg_ratio")
    metrics["peg_ratio"] = {
        "value": round(peg, 2) if peg is not None else None,
        "flag": _flag(
            peg,
            bullish_condition=peg is not None and 0 < peg < 1.5,
            bearish_condition=peg is not None and peg > 3,
        ),
        "note": (
            "Potentially undervalued relative to growth" if peg and 0 < peg < 1.5
            else "Fairly valued" if peg and 1.5 <= peg <= 3
            else "Growth premium high" if peg and peg > 3
            else "Data unavailable"
        ),
    }

    # Current Ratio (liquidity)
    cr = data.get("current_ratio")
    metrics["current_ratio"] = {
        "value": round(cr, 2) if cr is not None else None,
        "flag": _flag(
            cr,
            bullish_condition=cr is not None and cr > 1.5,
            bearish_condition=cr is not None and cr < 1.0,
        ),
        "note": (
            "Strong liquidity" if cr and cr > 1.5
            else "Adequate liquidity" if cr and 1.0 <= cr <= 1.5
            else "Potential liquidity risk" if cr and cr < 1.0
            else "Data unavailable"
        ),
    }

    # Overall scoring
    flag_scores = {"bullish": 1, "neutral": 0, "bearish": -1, "unavailable": 0}
    total_score = sum(flag_scores.get(m["flag"], 0) for m in metrics.values())
    available = sum(1 for m in metrics.values() if m["flag"] != "unavailable")
    max_score = available if available > 0 else 1

    normalized = total_score / max_score
    if normalized > 0.3:
        overall = "bullish"
    elif normalized < -0.3:
        overall = "bearish"
    else:
        overall = "neutral"

    bullish_count = sum(1 for m in metrics.values() if m["flag"] == "bullish")
    bearish_count = sum(1 for m in metrics.values() if m["flag"] == "bearish")

    return {
        "metrics": metrics,
        "score": round(normalized, 2),
        "overall": overall,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": available - bullish_count - bearish_count,
        "summary": f"{bullish_count} bullish, {bearish_count} bearish, {available - bullish_count - bearish_count} neutral metrics",
    }
