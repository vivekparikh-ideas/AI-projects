"""Portfolio Ledger tools: the independent shadow accountant. M1 keeps the books in memory; M3 uses SQLite."""

from __future__ import annotations

from nexus.data import provider
from nexus.schemas import ExecutionReceipt, PortfolioSnapshot, Position, TaxLot, ToolResult


def _result(tool: str, source: str, data: dict, evidence: str) -> ToolResult:
    return ToolResult(tool=tool, source=source, as_of=provider().as_of(), data=data, evidence=evidence)


def get_broker_positions(ticker: str, snapshot: PortfolioSnapshot, receipt: ExecutionReceipt) -> ToolResult:
    """The simulator holds prior shares plus today's simulated fills (no broker exists, D-039)."""
    prior = sum(p.shares for p in snapshot.positions if p.ticker == ticker)
    shares = round(prior + receipt.shares_filled, 4)
    return _result("get_broker_positions", "simulator", {"ticker": ticker, "shares": shares}, f"Simulator holds {shares:g} {ticker} shares after the fill")


def reconcile_positions(ticker: str, ledger_shares: float, broker_shares: float) -> ToolResult:
    ok = abs(ledger_shares - broker_shares) < 1e-6
    verdict = "match ✓" if ok else "MISMATCH: new trades paused"
    return _result("reconcile_positions", "ledger", {"reconciled": ok}, f"Ledger {ledger_shares:g} vs simulated fills {broker_shares:g} {ticker} shares: {verdict}")


def book_tax_lot(ticker: str, shares: int, cost_basis: float, existing_lots: int) -> ToolResult:
    today = provider().as_of()
    lot = TaxLot(lot_id=f"{ticker}-{today}-{existing_lots + 1:03d}", ticker=ticker, shares=shares, cost_basis=cost_basis, acquired=today, term="short_term")
    return _result("book_tax_lot", "ledger", lot.model_dump(), f"Lot {lot.lot_id} | {shares} sh @ ${cost_basis:.3f} | short-term")


def settle_cash(cash_before: float, notional: float, commissions: float) -> ToolResult:
    after = round(cash_before - notional - commissions, 2)
    return _result("settle_cash", "ledger", {"cash_before": cash_before, "cash_after": after}, f"Cash ${cash_before:,.2f} → ${after:,.2f} (settles T+1)")


def mark_to_market_nav(nav_before: float, notional: float, commissions: float, shares: int, mark: float) -> ToolResult:
    """M1 marks only the new lot; other positions keep their marks until the close (M3 marks all)."""
    after = round(nav_before - notional - commissions + shares * mark, 2)
    return _result("mark_to_market_nav", "ledger", {"nav_before": nav_before, "nav_after": after, "mark": mark}, f"NAV ${nav_before:,.2f} → ${after:,.2f} (marked at ${mark:.2f})")


def apply_fill(snapshot: PortfolioSnapshot, ticker: str, shares: int, mark: float, cash_after: float, nav_after: float, lot: TaxLot) -> PortfolioSnapshot:
    """Return the post-trade snapshot with the new position, cash and NAV."""
    positions: list[Position] = []
    found = False
    for p in snapshot.positions:
        if p.ticker == ticker:
            p = p.model_copy(update={"shares": p.shares + shares, "price": mark})
            found = True
        positions.append(p)
    if not found:
        positions.append(Position(ticker=ticker, shares=shares, price=mark, weight_pct=0.0))
    positions = [p.model_copy(update={"weight_pct": round(p.shares * p.price / nav_after * 100, 2)}) for p in positions]
    return snapshot.model_copy(update={"positions": positions, "settled_cash": cash_after, "nav": nav_after, "tax_lots": [*snapshot.tax_lots, lot]})
