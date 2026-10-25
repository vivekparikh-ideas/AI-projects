"""Single source of truth for which role may call which tool (D-006, D-015, D-017).

No web search exists anywhere. LLM roles (research_analyst, portfolio_manager) hold only
`read` tools; write and irreversible tools belong to deterministic roles.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langsmith import traceable

from nexus.schemas import AgentId
from nexus.telemetry import micro_action
from nexus.tools import execution, ledger, pm, research, risk

Permission = Literal["read", "write", "irreversible"]
LLM_ROLES: frozenset[AgentId] = frozenset({"research_analyst", "portfolio_manager"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    code: str
    permission: Permission
    label: str
    fn: Callable[..., Any]


def _spec(code: str, fn: Callable[..., Any], label: str, permission: Permission = "read") -> ToolSpec:
    return ToolSpec(name=fn.__name__, code=code, permission=permission, label=label, fn=fn)


REGISTRY: dict[AgentId, dict[str, ToolSpec]] = {
    "research_analyst": {s.name: s for s in [
        _spec("R1", research.sec_list_filings, "Listing recent SEC filings"),
        _spec("R2", research.sec_get_financials, "Parsing latest 10-K/10-Q financials"),
        _spec("R3", research.sec_get_filing_section, "Reading filing section"),
        _spec("R4", research.sec_get_insider_trades, "Scanning Form 4 insider trades"),
        _spec("R5", research.get_institutional_holders, "Checking 13F institutional flows"),
        _spec("R6", research.get_cap_table, "Reviewing cap table & dilution"),
        _spec("R7", research.get_valuation, "Pulling valuation multiples"),
        _spec("R8", research.get_price_history, "Loading 1-year price history"),
        _spec("R9", research.compute_technicals, "Computing technical setup"),
        _spec("R10", research.get_earnings_transcript, "Fetching earnings call transcript"),
        _spec("R11", research.compute_scorecard, "Scoring fundamentals (deterministic)"),
        _spec("SUBMIT", research.submit_dossier, "Submitting dossier (schema + grounding check)"),
    ]},
    "portfolio_manager": {s.name: s for s in [
        _spec("P1", pm.get_portfolio_snapshot, "Loading portfolio snapshot"),
        _spec("P2", pm.get_fund_mandate, "Reading fund mandate"),
        _spec("P3", pm.compute_correlation_beta, "Checking correlation & beta overlap"),
        _spec("P4", pm.compute_realized_vol, "Measuring realized volatility"),
        _spec("P5", pm.size_position, "Sizing position (volatility-adjusted)"),
    ]},
    "risk_gate": {s.name: s for s in [
        _spec("K1", risk.check_concentration, "Single-name concentration"),
        _spec("K2", risk.check_cash_and_margin, "Settled cash & margin"),
        _spec("K3", risk.check_wash_sale, "30-day wash-sale scan"),
        _spec("K4", risk.compute_marginal_var, "Marginal 99% VaR stress test"),
    ]},
    "execution_trader": {s.name: s for s in [
        _spec("E1", execution.get_nbbo_quote, "Checking bid/ask spread"),
        _spec("E2", execution.plan_twap_slices, "Planning TWAP slices"),
        _spec("E3", execution.submit_limit_order, "Routing limit slice", "irreversible"),
        _spec("E4", execution.poll_order_status, "Confirming fill"),
        _spec("E5", execution.compute_slippage_bps, "Measuring slippage vs arrival"),
    ]},
    "portfolio_ledger": {s.name: s for s in [
        _spec("L1", ledger.get_broker_positions, "Checking the simulated fills"),
        _spec("L2", ledger.reconcile_positions, "Reconciling ledger vs broker"),
        _spec("L3", ledger.book_tax_lot, "Booking tax lot", "write"),
        _spec("L4", ledger.settle_cash, "Updating cash", "write"),
        _spec("L5", ledger.mark_to_market_nav, "Marking NAV to market"),
    ]},
}

# (agent_id, tool name) for every call; tests use it to prove roles stay inside the registry.
CALL_LOG: list[tuple[AgentId, str]] = []


def get_spec(agent_id: AgentId, name: str) -> ToolSpec:
    spec = REGISTRY.get(agent_id, {}).get(name)
    if spec is None:
        raise PermissionError(f"{agent_id} is not allowed to call {name!r}")
    return spec


def call(agent_id: AgentId, name: str, **kwargs: Any) -> Any:
    spec = get_spec(agent_id, name)
    CALL_LOG.append((agent_id, name))
    # Every tool runs inside a LangSmith tool span with its full inputs and output (D-044).
    traced = traceable(run_type="tool", name=name, metadata={"agent_id": agent_id, "code": spec.code, "permission": spec.permission})(spec.fn)
    return traced(**kwargs)


def use(run_id: str, agent_id: AgentId, name: str, *, label: str | None = None, **kwargs: Any) -> Any:
    """Call a registered tool inside a micro-action so the UI sees ⟳ then ✓ with evidence."""
    spec = get_spec(agent_id, name)
    with micro_action(run_id, agent_id, name, f"{spec.code} · {label or spec.label}") as ev:
        result = call(agent_id, name, **kwargs)
        if hasattr(result, "passed"):  # a risk rule: the check ran, but it may have failed
            ev.text = f"{'PASS' if result.passed else 'FAIL'} · {result.detail}"
        else:
            ev.text = getattr(result, "evidence", "")
        ev.source_label = getattr(result, "source_label", None)
        ev.source_url = getattr(result, "source_url", None)
    return result
