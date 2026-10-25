"""Node 4 — Execution Trader: deterministic broker worker, approved orders only (D-013)."""

from __future__ import annotations

from typing import Any

from nexus import explain
from nexus.schemas import ExecutionReceipt, FillSlice, HandoffSummary
from nexus.state import FundGraphState
from nexus.telemetry import emit_agent_started, micro_action, now_iso, record_handoff, ref, sha8
from nexus.tools import registry

AGENT = "execution_trader"


def execution_trader(state: FundGraphState) -> dict[str, Any]:
    run, intent = state.run_id, state.intent
    started = now_iso()
    emit_agent_started(run, AGENT)

    # The order sent must be exactly the intent the Risk Gate cleared.
    approved_ref = next(r for r in reversed(state.handoff_log) if r.agent_id == "risk_gate").consumed[0]
    with micro_action(run, AGENT, "approval_match", "Verifying order matches approved intent") as ev:
        if approved_ref.sha != sha8(intent):
            raise RuntimeError(f"order {sha8(intent)} differs from approved intent {approved_ref.sha}")
        ev.text = f"TradeIntent #{approved_ref.sha} matches the approved order"

    quote = registry.use(run, AGENT, "get_nbbo_quote", ticker=intent.ticker).data
    sizes = registry.use(run, AGENT, "plan_twap_slices", shares=intent.shares).data["slices"]
    client_order_id = f"{run}-{approved_ref.sha}"  # idempotent: a retry can't double-submit

    fills: list[FillSlice] = []
    for i, size in enumerate(sizes, start=1):
        order = registry.use(
            run, AGENT, "submit_limit_order", label=f"Routing limit slice {i}/{len(sizes)} ({size} sh)",
            client_order_id=client_order_id, ticker=intent.ticker, side=intent.action, shares=size,
            limit_price=intent.limit_price, bid=quote["bid"], seq=i,
        ).data
        fill = registry.use(run, AGENT, "poll_order_status", label=f"Confirming slice {i} fill", order=order).data
        fills.append(FillSlice(seq=fill["seq"], shares=fill["shares"], price=fill["price"]))

    filled = sum(f.shares for f in fills)
    notional = round(sum(f.shares * f.price for f in fills), 2)
    avg = round(notional / filled, 3)
    slip = registry.use(run, AGENT, "compute_slippage_bps", avg_fill=notional / filled, arrival=quote["mid"], side=intent.action).data["slippage_bps"]

    receipt = ExecutionReceipt(
        ticker=intent.ticker, side=intent.action, client_order_id=client_order_id,
        shares_requested=intent.shares, shares_filled=filled, fill_pct=round(filled / intent.shares * 100, 1),
        bid=quote["bid"], ask=quote["ask"], spread_bps=quote["spread_bps"], arrival_price=quote["mid"],
        avg_fill_price=avg, slippage_bps=slip, commissions=0.0, notional=notional, slices=fills,
    )
    handoff = HandoffSummary(
        signal=f"FILLED {receipt.fill_pct:.0f}% ({slip:+.1f} bps Slippage)",
        opinion=f"Ledger should book a {filled}-share {intent.ticker} lot at ${avg:,.3f} and reconcile with the broker.",
        why_rationale=f"A {quote['spread_bps']:.1f} bps spread allowed {len(fills)} passive limit slices, averaging ${avg:,.3f} vs ${quote['mid']:,.2f} arrival.",
    )
    record = record_handoff(
        run_id=run, seq=len(state.handoff_log) + 1, agent_id=AGENT, status="COMPLETED", started_at=started,
        consumed=[ref("portfolio_manager", intent), ref("risk_gate", state.risk)],
        output=receipt, handoff=handoff, plain=explain.execution(receipt),
    )
    return {"receipt": receipt, "handoff_log": [record]}
