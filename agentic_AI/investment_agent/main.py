#!/usr/bin/env python3
"""
Investment Agent — AI-powered stock analysis tool.

Usage:
    python main.py AAPL MSFT TSLA NVDA
"""
import sys
import os
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import box

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

from config import ANTHROPIC_API_KEY
from agents.orchestrator import analyze_stock
from report.generator import generate_html_report

console = Console()


def print_banner():
    console.print(Panel.fit(
        "[bold blue]Investment Agent[/bold blue]\n"
        "[dim]AI-powered stock analysis using Claude claude-sonnet-4-6[/dim]",
        border_style="blue",
    ))


def print_results_table(results: list):
    table = Table(title="Analysis Summary", box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Change (6mo)", justify="right", width=13)
    table.add_column("Recommendation", justify="center", width=16)
    table.add_column("Confidence", justify="center", width=12)
    table.add_column("Target", justify="right", width=10)

    color_map = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}
    conf_color = {"High": "green", "Medium": "yellow", "Low": "red"}

    for r in results:
        rec = r.get("recommendation", "HOLD")
        conf = r.get("confidence", "Medium")
        color = color_map.get(rec, "white")
        cc = conf_color.get(conf, "white")

        # Get price info from snapshot
        price_str = "N/A"
        change_str = "N/A"
        snap = r.get("data_snapshot", {})
        for key in ["get_price_history"]:
            if key in snap:
                import json
                d = json.loads(snap[key]) if isinstance(snap[key], str) else snap[key]
                price_str = f"${d.get('current_price', 'N/A')}"
                chg = d.get("period_change_pct", None)
                if chg is not None:
                    sign = "+" if chg >= 0 else ""
                    change_color = "green" if chg >= 0 else "red"
                    change_str = f"[{change_color}]{sign}{chg}%[/{change_color}]"

        table.add_row(
            r["ticker"],
            price_str,
            change_str,
            f"[{color}]{rec}[/{color}]",
            f"[{cc}]{conf}[/{cc}]",
            r.get("target_price", "N/A"),
        )

    console.print()
    console.print(table)


def main():
    if len(sys.argv) < 2:
        console.print("[red]Error:[/red] Please provide at least one ticker symbol.")
        console.print("Usage: python main.py AAPL MSFT TSLA")
        sys.exit(1)

    tickers = [t.upper().strip() for t in sys.argv[1:] if t.strip()]

    if not ANTHROPIC_API_KEY:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY not set. Create a .env file with your key.")
        sys.exit(1)

    print_banner()
    console.print(f"\nAnalyzing [bold]{', '.join(tickers)}[/bold]...\n")

    results = []

    for ticker in tickers:
        console.rule(f"[bold cyan]{ticker}[/bold cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Analyzing {ticker}...", total=None)

            def update_progress(msg: str):
                progress.update(task, description=f"[dim]{msg}[/dim]")

            try:
                result = analyze_stock(ticker, progress_callback=update_progress)
                results.append(result)

                rec = result.get("recommendation", "HOLD")
                conf = result.get("confidence", "Medium")
                target = result.get("target_price", "N/A")
                color_map = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}
                color = color_map.get(rec, "white")

                console.print(
                    f"  [bold]Result:[/bold] [{color}]{rec}[/{color}] | "
                    f"Confidence: {conf} | Target: {target} | "
                    f"Tools used: {len(result.get('tools_used', []))}"
                )
            except Exception as e:
                console.print(f"  [red]Error analyzing {ticker}:[/red] {e}")
                results.append({
                    "ticker": ticker,
                    "recommendation": "ERROR",
                    "confidence": "N/A",
                    "target_price": "N/A",
                    "reasoning": f"Analysis failed: {e}",
                    "data_snapshot": {},
                    "tools_used": [],
                })

    # Print summary table
    valid_results = [r for r in results if r.get("recommendation") != "ERROR"]
    if valid_results:
        print_results_table(valid_results)

    # Generate HTML report
    report_date = date.today().strftime("%Y%m%d")
    output_path = os.path.join(os.path.dirname(__file__), f"investment_report_{report_date}.html")

    console.print()
    with console.status("[bold green]Generating HTML report...[/bold green]"):
        generate_html_report(results, output_path)

    console.print(f"\n[bold green]Report saved:[/bold green] {output_path}")
    console.print("\n[dim]Disclaimer: This report is for informational purposes only and does not constitute financial advice.[/dim]")


if __name__ == "__main__":
    main()
