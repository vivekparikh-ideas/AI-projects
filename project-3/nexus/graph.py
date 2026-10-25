"""LangGraph spine: sequential pipeline with bounded LLM-decided feedback loops (D-001, D-018, D-021)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from nexus import mock_data
from nexus.data import provider
from nexus.fund import FundConfig, mandate_for
from nexus.nodes import execution_trader, finalize, fund_check, hitl_approval, portfolio_ledger, portfolio_manager, request_approval, research_analyst, risk_gate
from nexus.schemas import PortfolioSnapshot, Position, RealizedLoss, TradeIntent
from nexus.state import FundGraphState


def route_after_pm(state: FundGraphState) -> str:
    return {"research": "research_analyst", "risk": "fund_check"}.get(state.pm_route or "", "finalize")


def route_after_fund_check(state: FundGraphState) -> str:
    return "risk_gate" if state.fund_route == "risk" else "finalize"


def route_after_research(state: FundGraphState) -> str:
    return END if state.journey == "research" else "portfolio_manager"


def route_after_risk(state: FundGraphState) -> str:
    if state.journey == "whatif":
        return END  # a what-if never trades (D-023)
    return {"execute": "request_approval", "revise": "portfolio_manager"}.get(state.risk_route or "", "finalize")


def route_after_approval(state: FundGraphState) -> str:
    return {"execute": "execution_trader", "recheck": "risk_gate"}.get(state.approval_route or "", "finalize")


def build_graph(entry: Literal["research_analyst", "portfolio_manager", "risk_gate"] = "research_analyst", checkpointer: Any = None):
    """`entry="portfolio_manager"` resumes a run after the user supplies a fund (no re-research);
    `entry="risk_gate"` runs a what-if check on a hypothetical order.

    Approval pauses with `interrupt()`, which needs a checkpointer and a `thread_id` in the config
    (the API and CLI pass one). Without one, run with `configurable.approval = "auto"` (tests, evals)."""
    g = StateGraph(FundGraphState)
    g.add_node("research_analyst", research_analyst)
    g.add_node("portfolio_manager", portfolio_manager)
    g.add_node("fund_check", fund_check)
    g.add_node("risk_gate", risk_gate)
    g.add_node("request_approval", request_approval)
    g.add_node("hitl_approval", hitl_approval)
    g.add_node("execution_trader", execution_trader)
    g.add_node("portfolio_ledger", portfolio_ledger)
    g.add_node("finalize", finalize)

    g.add_edge(START, entry)
    g.add_conditional_edges("research_analyst", route_after_research, ["portfolio_manager", END])
    g.add_conditional_edges("portfolio_manager", route_after_pm, ["research_analyst", "fund_check", "finalize"])
    g.add_conditional_edges("fund_check", route_after_fund_check, ["risk_gate", "finalize"])
    g.add_conditional_edges("risk_gate", route_after_risk, ["request_approval", "portfolio_manager", "finalize", END])
    g.add_edge("request_approval", "hitl_approval")
    g.add_conditional_edges("hitl_approval", route_after_approval, ["execution_trader", "risk_gate", "finalize"])
    g.add_edge("execution_trader", "portfolio_ledger")
    g.add_edge("portfolio_ledger", END)
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def checkpoint_serde():
    """Checkpoint serializer that allows exactly the Nexus contract types in saved state (and nothing else)."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from nexus import schemas

    names = [n for n, v in vars(schemas).items() if isinstance(v, type) and issubclass(v, schemas.Contract) and v.__module__ == schemas.__name__]
    return JsonPlusSerializer(allowed_msgpack_modules=[("nexus.schemas", n) for n in names])


def fixture_portfolio() -> PortfolioSnapshot:
    """The $2.45M sample fund used by the M1 reference runs."""
    p = mock_data.PORTFOLIO
    positions = [
        Position(ticker=t, shares=int(round(w / 100 * p["nav"] / px)), price=px, weight_pct=w)
        for t, w, px in p["positions"]
    ]
    return PortfolioSnapshot(
        as_of=p["as_of"], nav=p["nav"], settled_cash=p["settled_cash"], beta=p["beta"],
        current_var_pct=p["current_var_pct"], positions=positions,
        realized_losses=[RealizedLoss(**x) for x in p["realized_losses"]],
    )


def initial_state(ticker: str, fixture: str = "default", fund: FundConfig | Literal["sample"] | None = None, journey: str = "evaluate") -> FundGraphState:
    """`fund=None` means the user skipped setup: no invented money (D-021)."""
    ticker = ticker.upper()
    if provider().name == "fixture":
        mock_data.ticker_data(ticker)  # fail fast with the list of available fixtures
    if fund == "sample":
        portfolio, mandate = fixture_portfolio(), mandate_for("balanced")
    elif fund is None:
        portfolio, mandate = None, mandate_for("balanced")
    else:
        portfolio, mandate = fund.snapshot(), fund.mandate
    return FundGraphState(run_id=f"run-{uuid.uuid4().hex[:8]}", ticker=ticker, fixture=fixture, portfolio=portfolio, mandate=mandate, journey=journey)


def whatif_state(ticker: str, amount: float, fund: FundConfig | Literal["sample"]) -> FundGraphState:
    """A hypothetical limit buy at the latest price for the Risk Gate to test; nothing is ever sent (D-023)."""
    state = initial_state(ticker, fund=fund, journey="whatif")
    price = round(provider().close(state.ticker), 2)
    shares = int(amount // price)
    if shares < 1:
        raise ValueError(f"${amount:,.0f} buys less than one share of {state.ticker} at ${price:,.2f}")
    intent = TradeIntent(
        action="BUY", ticker=state.ticker, target_weight_pct=round(shares * price / state.portfolio.nav * 100, 2),
        dollar_amount=round(shares * price, 2), shares=shares, limit_price=price, stop_loss_price=round(price * 0.9, 2),
        rationale=f"What-if: ${amount:,.0f} of {state.ticker}",
    )
    return state.model_copy(update={"intent": intent})


def resume_with_fund(final: dict[str, Any], fund: FundConfig) -> FundGraphState:
    """Continue an advice-only run once the user enters a fund: keep research, re-enter at the PM.

    Drops the AWAITING_FUND placeholders; M3 replaces this with a checkpointed interrupt/resume.
    """
    log = [r for r in final["handoff_log"] if r.status != "AWAITING_FUND"]
    keep = {k: v for k, v in final.items() if k in FundGraphState.model_fields and k not in ("handoff_log", "pm_route", "fund_route")}
    return FundGraphState(**{**keep, "handoff_log": log, "portfolio": fund.snapshot(), "mandate": fund.mandate})
