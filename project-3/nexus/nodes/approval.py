"""Founder approval (D-009, D-013, D-043): the run pauses with the exact order until the user decides.

Two nodes, both shown under The Vault:
- `request_approval` fixes the ticket (order, price and time at issue) in state.
- `hitl_approval` pauses with LangGraph `interrupt()`. A resume re-runs this node from its start, so it
  emits nothing before the pause (the API announces the pause) and reads the issue time and price from the saved ticket.

On approve, a ticket older than 15 minutes or a price move over 0.5% sends the order back to The Vault
for a fresh check (at most MAX_APPROVAL_RECHECKS times). `configurable.approval = "auto"` approves without
pausing; only tests, evals and design exports use it, never the API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from nexus.data import provider
from nexus.schemas import ApprovalTicket
from nexus.state import APPROVAL_MAX_DRIFT_PCT, APPROVAL_TTL_MIN, MAX_APPROVAL_RECHECKS, FundGraphState
from nexus.telemetry import micro_action, sha8

AGENT = "risk_gate"


def _mid(ticker: str) -> float:
    q = provider().quote(ticker)
    return round((q["bid"] + q["ask"]) / 2, 4)


def _clock(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M UTC")


def request_approval(state: FundGraphState) -> dict[str, Any]:
    intent, risk = state.intent, state.risk
    issued = datetime.now(timezone.utc)
    var_rule = next(r for r in risk.rules if r.name == "marginal_var")
    with micro_action(state.run_id, AGENT, "hitl_ticket", "Preparing your approval ticket") as ev:
        ticket = ApprovalTicket(
            ticket_id=f"{state.run_id}-{sha8(intent)}-{state.approval_rechecks}",
            ticker=intent.ticker, action=intent.action, shares=intent.shares, limit_price=intent.limit_price,
            dollar_amount=intent.dollar_amount, stop_loss_price=intent.stop_loss_price,
            target_weight_pct=intent.target_weight_pct, rules_passed=risk.passed_count, rules_total=len(risk.rules),
            var_after_pct=risk.var_after_pct, var_limit_pct=var_rule.limit, price_at_issue=_mid(intent.ticker),
            issued_at=issued.isoformat(timespec="seconds"),
            expires_at=(issued + timedelta(minutes=APPROVAL_TTL_MIN)).isoformat(timespec="seconds"),
            max_drift_pct=APPROVAL_MAX_DRIFT_PCT,
            summary=f"Simulate a {intent.action.lower()} of {intent.shares} {intent.ticker} shares at up to ${intent.limit_price:,.2f} (about ${intent.dollar_amount:,.0f}), with a stop-loss at ${intent.stop_loss_price:,.2f}.",
        )
        ev.text = f"{ticket.action} {ticket.shares} {ticket.ticker} ≤ ${ticket.limit_price:,.2f} · waiting for you until {_clock(ticket.expires_at)}"
    return {"approval": ticket, "approval_route": None}


def hitl_approval(state: FundGraphState, config: RunnableConfig) -> dict[str, Any]:
    ticket = state.approval
    if config.get("configurable", {}).get("approval") == "auto":
        reply: dict[str, Any] = {"decision": "approve", "auto": True}
    else:
        reply = interrupt(ticket.model_dump())  # the run stops here until POST /approve (or the CLI prompt)

    with micro_action(state.run_id, AGENT, "hitl_approval", "Your approval") as ev:
        if reply.get("decision") != "approve":
            ev.text = "FAIL · You rejected the simulated trade. Nothing was traded."
            return {"approval_route": "rejected"}
        if reply.get("auto"):
            ev.text = "Approved automatically (test or eval run)"
            return {"approval_route": "execute"}
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ticket.issued_at)).total_seconds() / 60
        drift = abs(_mid(ticket.ticker) - ticket.price_at_issue) / ticket.price_at_issue * 100
        if age_min <= APPROVAL_TTL_MIN and drift <= ticket.max_drift_pct:
            ev.text = f"You approved after {age_min:.0f} min · price moved {drift:.2f}% (limit {ticket.max_drift_pct:g}%)"
            return {"approval_route": "execute"}
        why = f"{age_min:.0f} min old (limit {APPROVAL_TTL_MIN})" if age_min > APPROVAL_TTL_MIN else f"price moved {drift:.2f}% (limit {ticket.max_drift_pct:g}%)"
        if state.approval_rechecks >= MAX_APPROVAL_RECHECKS:
            ev.text = f"FAIL · Approval expired: {why}. Recheck limit reached; nothing was traded."
            return {"approval_route": "expired"}
        ev.text = f"FAIL · Approval expired: {why}. The Vault re-checks before anything is simulated."
        return {"approval_route": "recheck", "approval_rechecks": state.approval_rechecks + 1}
