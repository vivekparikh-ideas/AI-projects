"""Node 5 — Portfolio Ledger: independent shadow accountant (deterministic)."""

from __future__ import annotations

from typing import Any

from nexus import explain
from nexus.data import provider
from nexus.schemas import HandoffSummary, LedgerUpdate, TaxLot
from nexus.state import FundGraphState
from nexus.telemetry import emit_agent_started, now_iso, record_handoff, ref
from nexus.tools import registry
from nexus.tools.ledger import apply_fill

AGENT = "portfolio_ledger"


def _short(x: float) -> str:
    return f"${x / 1e6:.3f}M" if x >= 1e6 else f"${x / 1e3:.1f}k"


def portfolio_ledger(state: FundGraphState) -> dict[str, Any]:
    run, rc, snap = state.run_id, state.receipt, state.portfolio
    started = now_iso()
    emit_agent_started(run, AGENT)

    broker = registry.use(run, AGENT, "get_broker_positions", ticker=rc.ticker, snapshot=snap, receipt=rc).data["shares"]
    ledger_shares = sum(p.shares for p in snap.positions if p.ticker == rc.ticker) + rc.shares_filled
    reconciled = registry.use(run, AGENT, "reconcile_positions", ticker=rc.ticker, ledger_shares=ledger_shares, broker_shares=broker).data["reconciled"]
    lot = TaxLot(**registry.use(run, AGENT, "book_tax_lot", ticker=rc.ticker, shares=rc.shares_filled, cost_basis=rc.avg_fill_price, existing_lots=len(snap.tax_lots)).data)
    cash_after = registry.use(run, AGENT, "settle_cash", cash_before=snap.settled_cash, notional=rc.notional, commissions=rc.commissions).data["cash_after"]
    mark = provider().close(rc.ticker)
    nav_after = registry.use(run, AGENT, "mark_to_market_nav", nav_before=snap.nav, notional=rc.notional, commissions=rc.commissions, shares=rc.shares_filled, mark=mark).data["nav_after"]

    update = LedgerUpdate(
        ticker=rc.ticker, tax_lot=lot, broker_shares=int(round(broker)), ledger_shares=int(round(ledger_shares)), reconciled=reconciled,
        cash_before=snap.settled_cash, cash_after=cash_after, nav_before=snap.nav, nav_after=nav_after, mark_price=mark,
    )
    handoff = HandoffSummary(
        signal=f"BOOKED · NAV {_short(nav_after)} · {'Reconciled ✓' if reconciled else 'MISMATCH ✗'}",
        opinion="No action needed; the portfolio is up to date." if reconciled else "Pause new simulated trades until the ledger and the simulated fills agree.",
        why_rationale=f"The ledger and the simulated fills agree on {update.ledger_shares:,} {rc.ticker} shares; cash fell by the ${rc.notional:,.2f} simulated, and the new lot is marked at ${mark:.2f}.",
    )
    record = record_handoff(
        run_id=run, seq=len(state.handoff_log) + 1, agent_id=AGENT, status="COMPLETED", started_at=started,
        consumed=[ref("execution_trader", rc)], output=update, handoff=handoff, plain=explain.ledger(update),
    )
    return {"ledger": update, "portfolio": apply_fill(snap, rc.ticker, rc.shares_filled, mark, cash_after, nav_after, lot), "handoff_log": [record]}
