import anthropic
from config import MODEL, ANTHROPIC_API_KEY, MAX_AGENT_ITERATIONS
from agents.tools import TOOL_SCHEMAS, dispatch_tool

SYSTEM_PROMPT = """You are a professional investment analyst with deep expertise in technical and fundamental analysis. Your goal is to provide rigorous, data-driven stock recommendations.

## Analysis Framework
For each stock, you MUST use ALL of the following tools before making a recommendation:
1. `get_price_history` — Understand recent price action and trend
2. `calculate_technical_indicators` — RSI, MACD, Bollinger Bands, Moving Averages, Volume
3. `get_fundamental_data` — P/E, EPS, revenue, margins, debt, ROE
4. `get_company_info` — Sector, industry, business model
5. `get_recent_news` — Sentiment and catalysts
6. `get_analyst_recommendations` — Professional consensus

## Weighting Framework
- Price trend & momentum: 30%
- Technical indicators: 30%
- Fundamental quality: 25%
- News sentiment & catalysts: 15%

## Recommendation Format
After gathering ALL data, provide your recommendation in this EXACT format:

**RECOMMENDATION: [BUY/SELL/HOLD] | Confidence: [High/Medium/Low] | Target: $[price]**

Then provide 2-3 paragraphs covering:
1. **Technical Analysis**: Describe price action, trend, key indicator signals (RSI, MACD, Bollinger Bands, MAs)
2. **Fundamental Analysis**: Discuss valuation metrics, growth, profitability, and balance sheet health
3. **Catalysts & Risks**: Key news, analyst sentiment, upcoming catalysts, and main risk factors

## Guidelines
- Be specific with numbers (e.g., "RSI at 67, approaching overbought territory")
- Acknowledge uncertainties — avoid overconfidence
- Consider sector context when evaluating fundamentals
- If data is missing, note it and adjust confidence accordingly
- Confidence: High = strong signals across 4+ categories; Medium = mixed signals; Low = limited data or conflicting signals
- Target price: Based on technical resistance/support levels and fundamental valuation (if data supports it), otherwise state "Not determinable"
"""


def analyze_stock(ticker: str, progress_callback=None) -> dict:
    """
    Run the agentic analysis loop for a single ticker.
    Returns dict with ticker, recommendation, confidence, reasoning, data_snapshot.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {
            "role": "user",
            "content": f"Please analyze {ticker.upper()} stock and provide a comprehensive investment recommendation. Use all available tools to gather data before making your recommendation.",
        }
    ]

    tools_used = []
    data_snapshot = {}
    iteration = 0
    final_text = ""

    while iteration < MAX_AGENT_ITERATIONS:
        iteration += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Collect text content from this response
        text_parts = []
        tool_use_blocks = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        if text_parts:
            final_text = "\n".join(text_parts)

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # Process tool calls
        tool_results = []
        for tool_block in tool_use_blocks:
            tool_name = tool_block.name
            tool_input = tool_block.input

            if progress_callback:
                progress_callback(f"Calling tool: {tool_name}")

            tools_used.append(tool_name)
            result_json = dispatch_tool(tool_name, tool_input)

            # Store in data snapshot
            data_snapshot[tool_name] = result_json

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result_json,
            })

        # Append assistant response and tool results to messages
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Parse the final recommendation from the text
    recommendation = _parse_recommendation(final_text)

    return {
        "ticker": ticker.upper(),
        "recommendation": recommendation["action"],
        "confidence": recommendation["confidence"],
        "target_price": recommendation["target"],
        "reasoning": final_text,
        "tools_used": tools_used,
        "data_snapshot": data_snapshot,
        "iterations": iteration,
    }


def _parse_recommendation(text: str) -> dict:
    """Extract recommendation, confidence, and target from the agent's response text."""
    import re

    action = "HOLD"
    confidence = "Medium"
    target = "N/A"

    # Look for the structured recommendation line
    pattern = r"\*\*RECOMMENDATION:\s*(BUY|SELL|HOLD)\s*\|\s*Confidence:\s*(High|Medium|Low)\s*\|\s*Target:\s*\$?([\d,.]+|Not determinable|N/A)\*\*"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        action = match.group(1).upper()
        confidence = match.group(2).capitalize()
        target_str = match.group(3).strip()
        if target_str.lower() in ("not determinable", "n/a", ""):
            target = "N/A"
        else:
            target = f"${target_str.replace(',', '')}"
    else:
        # Fallback: look for keywords
        upper_text = text.upper()
        if "RECOMMENDATION: BUY" in upper_text or "STRONG BUY" in upper_text:
            action = "BUY"
        elif "RECOMMENDATION: SELL" in upper_text or "STRONG SELL" in upper_text:
            action = "SELL"
        elif "RECOMMENDATION: HOLD" in upper_text:
            action = "HOLD"

        if "CONFIDENCE: HIGH" in upper_text:
            confidence = "High"
        elif "CONFIDENCE: LOW" in upper_text:
            confidence = "Low"

    return {"action": action, "confidence": confidence, "target": target}
