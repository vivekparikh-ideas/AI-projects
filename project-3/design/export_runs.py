"""Export M1 runs as compact replay data for the Mission Control prototype.

    PYTHONPATH=. .venv/bin/python design/export_runs.py runs/replay.json
"""
import json, sys
from nexus.fund import FundConfig
from nexus.graph import build_graph, initial_state, resume_with_fund

NAMES = {"research_analyst": "Research Analyst", "portfolio_manager": "Portfolio Manager", "risk_gate": "Risk Gate", "execution_trader": "Execution Trader", "portfolio_ledger": "Portfolio Ledger"}
# (key, ticker, fixture, fund, blurb). fund: None = setup skipped, "sample" = $2.45M demo fund.
SCENARIOS = [
    ("nvda_nofund", "NVDA", "default", None, "No fund set: advice, then The Vault asks for cash"),
    ("nvda", "NVDA", "default", "sample", "Happy path: ReAct research → buy → filled"),
    ("amd", "AMD", "default", "sample", "Risk fail → PM resizes → passes"),
    ("aapl", "AAPL", "default", "sample", "Wash-sale hard reject"),
    ("nvda_more", "NVDA", "needs_more", "sample", "PM sends a question back to Research"),
]
RESUME_CASH = 100_000  # the cash the prototype's fund card enters for the no-fund run

def chip(r):
    o, t = r.get("output"), r.get("output_type")
    if r["status"] == "SKIPPED": return "Skipped"
    if t == "ResearchDossier": return f"Dossier · {o['conviction_score']:.1f}/10"
    if t == "TradeIntent": return "HOLD" if o["action"] == "HOLD" else f"{o['action']} {o['shares']} sh · {o['target_weight_pct']:.1f}%"
    if t == "RiskCheckResult":
        n = sum(x["passed"] for x in o["rules"]); return f"{n}/4 rules · {'cleared' if o['approved'] else 'blocked'}"
    if t == "ExecutionReceipt": return f"Filled {o['fill_pct']:.0f}% · {o['slippage_bps']:+.1f} bps"
    if t == "LedgerUpdate": return f"NAV ${o['nav_after']/1e6:.3f}M"
    if r["agent_id"] == "portfolio_manager": return "Question → Research"
    return r["status"].title()

def fields(r):
    o, t = r.get("output"), r.get("output_type")
    if not o: return []
    if t == "ResearchDossier":
        return [["Conviction", f"{o['conviction_score']:.1f} = {o['scorecard']['base_score']:.1f} {o['llm_adjustment']:+.1f}"], ["Bull case", o["bull_case"]], ["Bear case", o["bear_case"]], ["Follow-up tools", ", ".join(s["tool"] for s in o["agent_trace"]) or "none"], ["Fwd P/E", f"{o['valuation']['fwd_pe']:.1f}"], ["Spot / 200-DMA", f"${o['technicals']['spot']:.2f} / ${o['technicals']['dma200']:.2f}"]]
    if t == "TradeIntent":
        if o["action"] == "HOLD": return [["Action", "HOLD"], ["Why", o["rationale"]]]
        return [["Action", f"{o['action']} {o['ticker']}"], ["Shares", f"{o['shares']:,}"], ["Limit", f"${o['limit_price']:,.2f}"], ["Amount", f"${o['dollar_amount']:,.2f}"], ["Weight", f"{o['target_weight_pct']:.1f}% NAV"], ["Stop-loss", f"${o['stop_loss_price']:,.2f}"]]
    if t == "RiskCheckResult":
        return [[x["name"].replace("_", " "), ("PASS · " if x["passed"] else "FAIL · ") + x["detail"]] for x in o["rules"]]
    if t == "ExecutionReceipt":
        return [["Filled", f"{o['shares_filled']:,} / {o['shares_requested']:,} sh"], ["Avg price", f"${o['avg_fill_price']:,.3f}"], ["Arrival", f"${o['arrival_price']:,.2f}"], ["Slippage", f"{o['slippage_bps']:+.1f} bps"], ["Spread", f"{o['spread_bps']:.1f} bps"], ["Order ID", o["client_order_id"]]]
    if t == "LedgerUpdate":
        return [["Reconciled", "Yes" if o["reconciled"] else "NO"], ["Tax lot", f"{o['tax_lot']['lot_id']} · {o['tax_lot']['shares']} sh @ ${o['tax_lot']['cost_basis']:.3f}"], ["Cash", f"${o['cash_before']:,.2f} → ${o['cash_after']:,.2f}"], ["NAV", f"${o['nav_before']:,.2f} → ${o['nav_after']:,.2f}"]]
    return []

def snapshot_metrics(p):
    if p is None:
        return None
    gross = sum(x["weight_pct"] for x in p.model_dump()["positions"])
    return {"nav": p.nav, "cash": p.settled_cash, "gross": round(gross, 2)}

def record(graph, state):
    events, final = [], {}
    for mode, chunk in graph.stream(state, config={"configurable": {"speed": 0, "approval": "auto"}}, stream_mode=["custom", "values"]):
        if mode == "values": final = chunk; continue
        k = chunk["type"]
        if k == "agent_started":
            events.append({"k": "start", "a": chunk["agent_id"], "note": chunk["note"]})
        elif k == "micro_action":
            e = chunk["event"]
            events.append({"k": "act", "a": e["agent_id"], "id": e["action_id"], "l": e["action_label"], "s": e["status"], "e": e["evidence_snippet"]})
        elif k == "handoff_record":
            r = chunk["record"]
            consumed = [{"agent": NAMES[c["agent_id"]], "type": c["artifact_type"], "sha": c["sha"]} for c in r["consumed"]]
            events.append({"k": "rec", "a": r["agent_id"], "r": {
                "seq": r["seq"], "status": r["status"], "consumed": consumed,
                "produced": r["produced"], "output_type": r["output_type"], "output": r["output"],
                "handoff": r["handoff"], "plain": r["plain"], "chip": chip(r), "fields": fields(r)}})
    return events, final

out = {}
for key, ticker, fixture, fund, blurb in SCENARIOS:
    state = initial_state(ticker, fixture, fund)
    events, final = record(build_graph(), state)
    out[key] = {"key": key, "ticker": ticker, "fixture": fixture, "fund": fund or "none", "title": f"Evaluate {ticker}", "blurb": blurb,
                "start": snapshot_metrics(state.portfolio), "end": snapshot_metrics(final.get("portfolio")), "events": events}
    if fund is None:
        resumed = resume_with_fund(final, FundConfig(cash=RESUME_CASH))
        r_events, r_final = record(build_graph(entry="portfolio_manager"), resumed)
        out[key + "_resume"] = {"key": key + "_resume", "ticker": ticker, "fixture": fixture, "fund": f"cash {RESUME_CASH}", "title": f"Evaluate {ticker}",
                                "blurb": f"Resumed with ${RESUME_CASH:,} cash", "start": snapshot_metrics(resumed.portfolio), "end": snapshot_metrics(r_final.get("portfolio")), "events": r_events}
json.dump(out, open(sys.argv[1], "w"), separators=(",", ":"))
print({k: len(v["events"]) for k, v in out.items()})
