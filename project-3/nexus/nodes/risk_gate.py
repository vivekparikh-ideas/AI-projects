"""Node 3 — Pre-Trade Risk Gate: deterministic assertions only, no LLM (D-002, D-018)."""

from __future__ import annotations

from typing import Any

from nexus import explain
from nexus.schemas import HandoffSummary, RiskCheckResult
from nexus.state import MAX_RISK_REVISIONS, FundGraphState
from nexus.telemetry import emit_agent_started, micro_action, now_iso, record_handoff, ref
from nexus.data import provider
from nexus.tools import registry

AGENT = "risk_gate"


def risk_gate(state: FundGraphState) -> dict[str, Any]:
    run, intent, snap, mandate = state.run_id, state.intent, state.portfolio, state.mandate
    started = now_iso()
    note = "fresh check: your approval expired" if state.approval_route == "recheck" else f"re-check {state.risk_revisions + 1}" if state.risk_revisions else ""
    emit_agent_started(run, AGENT, note)
    add_pct = intent.dollar_amount / snap.nav * 100
    with micro_action(run, AGENT, "fund_check", "Fund check") as ev:
        ev.text = f"Fund set: ${snap.nav:,.0f} value, ${snap.settled_cash:,.0f} cash, {len(snap.positions)} holdings"

    mk = provider().market(intent.ticker, {p.ticker: p.weight_pct for p in snap.positions})
    rules = [
        registry.use(run, AGENT, "check_concentration", ticker=intent.ticker, existing_pct=snap.weight_of(intent.ticker), add_pct=add_pct, limit_pct=mandate["max_single_name_pct"]),
        registry.use(run, AGENT, "check_cash_and_margin", dollar_amount=intent.dollar_amount, settled_cash=snap.settled_cash),
        registry.use(run, AGENT, "check_wash_sale", ticker=intent.ticker, realized_losses=snap.realized_losses, as_of=snap.as_of, window_days=int(mandate["wash_sale_window_days"])),
        registry.use(run, AGENT, "compute_marginal_var", ticker=intent.ticker, add_pct=add_pct, var_before_pct=snap.current_var_pct, limit_pct=mandate["max_var_pct"], realized_vol=mk["realized_vol"], corr_to_portfolio=mk["corr_to_portfolio"]),
    ]
    approved = all(r.passed for r in rules)
    failed = [r for r in rules if not r.passed]
    var_after = next(r.observed for r in rules if r.name == "marginal_var")

    if state.journey == "whatif":
        route, hitl = "whatif", "NOT_REQUIRED"
    elif approved:
        route, hitl = "execute", "PENDING"  # the run now pauses for the user's approval (D-043)
    elif all(r.resizable for r in failed) and state.risk_revisions < MAX_RISK_REVISIONS:
        route, hitl = "revise", "NOT_REQUIRED"
    else:
        route, hitl = "reject", "NOT_REQUIRED"

    result = RiskCheckResult(rules=rules, approved=approved, hitl_status=hitl, var_before_pct=snap.current_var_pct, var_after_pct=var_after)
    n, total = result.passed_count, len(rules)
    failed_names = ", ".join(r.name for r in failed)
    if route == "whatif":
        handoff = HandoffSummary(
            signal=f"WHAT-IF: {'PASSES' if approved else 'FAILS'} ({n}/{total} Rules)",
            opinion="What-if only: nothing will be traded.",
            why_rationale="; ".join(r.detail for r in rules) + ".",
        )
    elif route == "execute":
        handoff = HandoffSummary(
            signal=f"CLEARED ({n}/{total} Rules Passed)",
            opinion=f"Ask the founder to approve the {intent.shares}-share limit {intent.action.lower()}; no limits breached.",
            why_rationale=f"Position lands at {rules[0].observed:.2f}% vs {mandate['max_single_name_pct']:g}% cap and VaR moves {snap.current_var_pct:.2f}% → {var_after:.2f}% of NAV, under {mandate['max_var_pct']:g}%, with enough settled cash and no wash-sale conflict.",
        )
    elif route == "revise":
        handoff = HandoffSummary(
            signal=f"RESIZE REQUIRED ({n}/{total} Rules Passed)",
            opinion="PM should shrink the trade to clear the failed rule (one revision allowed).",
            why_rationale="; ".join(r.detail for r in failed) + ".",
        )
    else:
        handoff = HandoffSummary(
            signal=f"REJECTED ({n}/{total} Rules Passed)",
            opinion="Do not trade; the run ends here.",
            why_rationale="; ".join(r.detail for r in failed) + (" (not fixable by resizing)." if any(not r.resizable for r in failed) else " (revision limit reached)."),
        )

    record = record_handoff(
        run_id=run, seq=len(state.handoff_log) + 1, agent_id=AGENT, status="COMPLETED" if approved or route == "whatif" else "REJECTED",
        started_at=started, consumed=[ref("portfolio_manager", intent), ref("portfolio_ledger", snap)],
        output=result, handoff=handoff, plain=explain.risk(result, snap.nav, route),
    )
    update: dict[str, Any] = {"risk": result, "risk_route": None if route == "whatif" else route, "handoff_log": [record]}
    if route == "revise":
        update |= {"risk_feedback": failed, "risk_revisions": state.risk_revisions + 1}
    return update
