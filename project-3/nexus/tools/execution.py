"""Execution Trader tools. M1 simulates a passive paper broker; M3 routes to Alpaca paper only."""

from __future__ import annotations

from nexus.data import provider
from nexus.schemas import FillSlice, ToolResult

# Passive buy fills: at the bid, or one tick inside it (deterministic pattern for M1).
_FILL_TICKS = (0.01, 0.0, 0.0, 0.01, 0.0)


def _result(tool: str, data: dict, evidence: str) -> ToolResult:
    return ToolResult(tool=tool, source="simulated_paper_broker", as_of=provider().as_of(), data=data, evidence=evidence)


def get_nbbo_quote(ticker: str) -> ToolResult:
    q = provider().quote(ticker)
    mid = round((q["bid"] + q["ask"]) / 2, 4)
    spread_bps = (q["ask"] - q["bid"]) / mid * 1e4
    data = {"bid": q["bid"], "ask": q["ask"], "mid": mid, "spread_bps": round(spread_bps, 2)}
    return _result("get_nbbo_quote", data, f"Bid ${q['bid']:.2f} / ask ${q['ask']:.2f} | spread {spread_bps:.1f} bps | arrival ${mid:.2f}")


def plan_twap_slices(shares: int, n: int = 5) -> ToolResult:
    base, extra = divmod(shares, n)
    sizes = [base + (1 if i < extra else 0) for i in range(n)]
    return _result("plan_twap_slices", {"slices": sizes}, f"{n} passive limit slices: " + " · ".join(map(str, sizes)))


def submit_limit_order(client_order_id: str, ticker: str, side: str, shares: int, limit_price: float, bid: float, seq: int) -> ToolResult:
    """Irreversible in M3 (real paper order). M1 fills deterministically and never above the limit."""
    price = round(min(limit_price, bid + _FILL_TICKS[(seq - 1) % len(_FILL_TICKS)]), 2)
    data = {"order_id": f"{client_order_id}-{seq}", "seq": seq, "shares": shares, "price": price, "status": "submitted"}
    return _result("submit_limit_order", data, f"Slice {seq}: {shares} sh limit ${limit_price:.2f} submitted")


def poll_order_status(order: dict) -> ToolResult:
    fill = FillSlice(seq=order["seq"], shares=order["shares"], price=order["price"])
    return _result("poll_order_status", {**fill.model_dump(), "status": "filled"}, f"Filled {fill.shares} sh @ ${fill.price:.2f}")


def compute_slippage_bps(avg_fill: float, arrival: float, side: str) -> ToolResult:
    sign = 1 if side == "BUY" else -1
    bps = round(sign * (avg_fill - arrival) / arrival * 1e4, 1)
    word = "better" if bps < 0 else "worse"
    return _result("compute_slippage_bps", {"slippage_bps": bps}, f"Avg ${avg_fill:.3f} vs arrival ${arrival:.2f} = {bps:+.1f} bps ({word} than arrival)")
