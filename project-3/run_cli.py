"""Nexus Investment Engine CLI.

    python run_cli.py setup                                   # enter your cash, holdings and risk preset → fund.yaml
    python run_cli.py --ask "Evaluate NVDA" --live            # Claude + live SEC/yfinance data
    python run_cli.py --ask "Research TSLA" --live            # Ava only; nothing is traded
    python run_cli.py --ask "Can I add $50k of AMD?" --live   # The Vault checks a hypothetical order
    python run_cli.py --ticker NVDA --fund sample             # M1 fixture scenarios (no API cost); asks you to approve
    python run_cli.py --ticker NVDA --fund sample --approve yes   # approve without asking
    python run_cli.py --ticker NVDA --fund sample --json > runs/nvda.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from rich.console import Console
from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.text import Text

from nexus import data, policies, tracing
from nexus.fund import PRESETS, FundConfig, Holding, load_fund, save_fund
from nexus.graph import build_graph, checkpoint_serde, initial_state, resume_with_fund, whatif_state
from nexus.mock_data import TICKERS
from nexus.render import Renderer
from nexus.router import LATER, UnknownCommand, parse

ROOT = Path(__file__).resolve().parent
FUND_FILE = ROOT / "fund.yaml"


def _jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def _stream(graph, state, config, renderer: Renderer | None):
    """Run the graph, render live (or print JSON lines), and return the final state values."""
    final = {}
    for mode, chunk in graph.stream(state, config=config, stream_mode=["updates", "custom", "values"]):
        if mode == "values":
            final = chunk
        elif renderer is None:
            print(json.dumps({"mode": mode, "data": chunk}, default=_jsonable))
        else:
            renderer.handle(mode, chunk)
    return final


def _run_with_approval(graph, state, config, renderer: Renderer | None, approve: str, console: Console):
    """Stream the run; at each approval pause ask the user (or answer --approve yes/no) and resume (D-043)."""
    final = _stream(graph, state, config, renderer)
    while (pending := graph.get_state(config).interrupts):
        ticket = pending[0].value
        if approve == "ask" and console.is_terminal and renderer is not None:
            console.print(Text(f"\nYour call · {ticket['summary']}", style="bold yellow"))
            console.print(Text(f"{ticket['rules_passed']}/{ticket['rules_total']} safety checks passed · worst-day loss {ticket['var_after_pct']:.2f}% "
                               f"(limit {ticket['var_limit_pct']:g}%) · expires {datetime.fromisoformat(ticket['expires_at']).astimezone():%H:%M}", style="yellow"))
            try:
                decision = "approve" if Confirm.ask("Approve this simulated trade?", default=False) else "reject"
            except (EOFError, KeyboardInterrupt):
                decision = "reject"
        else:
            decision = "approve" if approve == "yes" else "reject"  # never approve silently
        final = _stream(graph, Command(resume={"decision": decision}), config, renderer)
    return final


def _ask_for_cash(console: Console) -> float | None:
    console.print(Text("\nThe Vault needs to know what you're working with before it can check this trade.", style="yellow"))
    try:
        answer = Prompt.ask("Enter your available cash to continue, or press Enter for advice only", default="", show_default=False)
    except (EOFError, KeyboardInterrupt):
        return None
    try:
        return float(answer.replace(",", "").replace("$", "")) if answer.strip() else None
    except ValueError:
        console.print(Text("That isn't a number; keeping this as advice only.", style="red"))
        return None


def setup(console: Console) -> int:
    """Interactive fund setup (D-021). Writes fund.yaml, which later runs pick up automatically."""
    console.print(Text("Set up your fund. Your agents use this to size trades and run the safety checks.\n", style="bold"))
    cash = FloatPrompt.ask("Available cash ($)")
    holdings: list[Holding] = []
    while Confirm.ask("Add a stock you already own?", default=False):
        ticker = Prompt.ask("  Ticker").strip().upper()
        shares = FloatPrompt.ask("  Shares")
        cost = FloatPrompt.ask("  Average cost per share ($)")
        holdings.append(Holding(ticker=ticker, shares=shares, cost_basis=cost))
    preset = Prompt.ask("How bold should they be?", choices=list(PRESETS), default="balanced")
    fund = FundConfig(cash=cash, holdings=holdings, preset=preset)
    save_fund(fund, FUND_FILE)
    limits = fund.mandate
    console.print(Text(f"\nSaved {FUND_FILE.name}: ${cash:,.0f} cash, {len(holdings)} holdings, {preset} "
                       f"(max {limits['max_single_name_pct']:g}% per stock, worst-day loss ≤ {limits['max_var_pct']:g}%).", style="green"))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    console = Console()
    if argv[:1] == ["setup"]:
        return setup(console)

    ap = argparse.ArgumentParser(description="Run Nexus. Fixture data by default; --live uses Claude and real market data.")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--ask", help='a command: "Evaluate NVDA", "Research TSLA", "Can I add $50k of AMD?"')
    what.add_argument("--ticker", help=f"shorthand for Evaluate <ticker> (fixtures: {', '.join(sorted(TICKERS))})")
    ap.add_argument("--fund", default="auto", help="auto (fund.yaml if present, else none) | none | sample | path/to/fund.yaml")
    ap.add_argument("--live", action="store_true", help="Claude for Ava and Marcus + live SEC EDGAR / yfinance data (costs API tokens)")
    ap.add_argument("--fixture", default="default", help="fixture scenario: default | needs_more | loop_forever")
    ap.add_argument("--speed", type=float, default=0.15, help="seconds each micro-action shows as in progress")
    ap.add_argument("--pro", action="store_true", help="show the 3-line financial handoff instead of plain English")
    ap.add_argument("--json", action="store_true", help="emit raw stream events as JSON lines (never prompts)")
    ap.add_argument("--approve", choices=["ask", "yes", "no"], default="ask", help="approval at the pause before Kai: ask (default; rejects when not a terminal) | yes | no")
    ap.add_argument("--show-payloads", action="store_true", help="print every handoff record and its full output at the end")
    args = ap.parse_args(argv)

    if args.live:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        data.use("live")
        policies.set_mode("claude")

    try:
        journey = parse(args.ask) if args.ask else parse(f"Evaluate {args.ticker}")
    except UnknownCommand as exc:
        console.print(Text(str(exc), style="red"))
        return 2
    if journey.kind in LATER:
        console.print(Text(LATER[journey.kind], style="yellow"))
        return 2

    if args.fund == "auto":
        fund = load_fund(FUND_FILE) if FUND_FILE.exists() else None
    else:
        fund = None if args.fund == "none" else "sample" if args.fund == "sample" else load_fund(args.fund)

    try:
        if journey.kind == "whatif":
            if fund is None:
                console.print(Text("A what-if needs your fund. Run `python run_cli.py setup` or pass --fund sample.", style="yellow"))
                return 2
            state, entry = whatif_state(journey.ticker, journey.amount, fund), "risk_gate"
        else:
            state, entry = initial_state(journey.ticker, args.fixture, fund, journey=journey.kind), "research_analyst"
    except (KeyError, ValueError) as exc:
        console.print(Text(str(exc.args[0]), style="red"))
        return 2

    checkpointer = InMemorySaver(serde=checkpoint_serde())  # the approval pause lives for this process only

    def config() -> dict:
        trace = tracing.run_config(run_id=state.run_id, journey=journey.kind, ticker=state.ticker, tags=["cli", policies.mode()])
        return {"configurable": {"speed": 0.0 if args.json else args.speed, "thread_id": uuid.uuid4().hex}, "recursion_limit": 40, **trace}

    if args.json:
        _run_with_approval(build_graph(entry=entry, checkpointer=checkpointer), state, config(), None, args.approve, console)
        return 0

    fund_note = "no fund set" if state.portfolio is None else f"fund ${state.portfolio.nav:,.0f}"
    mode_note = "live · Claude" if args.live else "fixtures"
    title = {"evaluate": "Evaluate", "research": "Research", "whatif": "What-if"}[journey.kind]
    console.print(Text(f"Nexus · {title} {state.ticker} · {fund_note} · {mode_note} · {state.run_id}", style="bold"))
    renderer = Renderer(console, pro=args.pro)
    final = _run_with_approval(build_graph(entry=entry, checkpointer=checkpointer), state, config(), renderer, args.approve, console)

    if final.get("fund_route") == "awaiting_fund" and console.is_terminal:
        cash = _ask_for_cash(console)
        if cash is not None:
            resumed = resume_with_fund(final, FundConfig(cash=cash))
            renderer.records = [r for r in renderer.records if r.status != "AWAITING_FUND"]
            console.print(Text(f"\nResuming with ${cash:,.0f} cash: Marcus sizes it, then The Vault checks it.", style="bold"))
            final = _run_with_approval(build_graph(entry="portfolio_manager", checkpointer=checkpointer), resumed, config(), renderer, args.approve, console)

    console.print()
    console.rule(Text(renderer.summary(final.get("approval_route")), style="bold"), align="left")
    if args.show_payloads:
        renderer.payload_table()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        tracing.flush()
