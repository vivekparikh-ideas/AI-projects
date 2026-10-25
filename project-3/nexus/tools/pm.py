"""Portfolio Manager tools P1–P5. size_position is the deterministic sizing formula (D-006)."""

from __future__ import annotations

import math

from nexus.data import provider
from nexus.mock_data import MANDATE
from nexus.schemas import PortfolioSnapshot, ToolResult


def _result(tool: str, source: str, data: dict, evidence: str) -> ToolResult:
    return ToolResult(tool=tool, source=source, as_of=provider().as_of(), data=data, evidence=evidence)


# P1
def get_portfolio_snapshot(snapshot: PortfolioSnapshot) -> ToolResult:
    evidence = (
        f"NAV ${snapshot.nav:,.0f} | settled cash ${snapshot.settled_cash:,.0f} | "
        f"{len(snapshot.positions)} positions | beta {snapshot.beta:.2f}"
    )
    return _result("get_portfolio_snapshot", "ledger", snapshot.model_dump(), evidence)


# P2
def get_fund_mandate(mandate: dict | None = None) -> ToolResult:
    m = mandate or MANDATE
    evidence = f"Max {m['max_single_name_pct']:g}% per name | VaR ≤ {m['max_var_pct']:g}% | target vol {m['target_vol']:.0%}"
    return _result("get_fund_mandate", "config", dict(m), evidence)


# P3
def compute_correlation_beta(ticker: str, holdings: dict[str, float]) -> ToolResult:
    """Overlap counts only stocks the fund actually holds; an empty fund has none (D-027)."""
    mk = provider().market(ticker, holdings)
    data = {k: mk[k] for k in ("max_corr_holding", "max_corr", "beta", "corr_to_portfolio")}
    overlap = f"Highest correlation: {mk['max_corr_holding']} {mk['max_corr']:.2f}" if mk["max_corr_holding"] else "No overlap with current holdings"
    evidence = f"{overlap} | beta {mk['beta']:.2f}"
    return _result("compute_correlation_beta", "computed", data, evidence)


# P4
def compute_realized_vol(ticker: str) -> ToolResult:
    vol = provider().market(ticker, {})["realized_vol"]
    return _result("compute_realized_vol", "computed", {"realized_vol": vol}, f"Realized volatility {vol:.0%} annualized")


# P5
def size_position(
    conviction: float,
    realized_vol: float,
    max_corr: float,
    nav: float | None,
    limit_price: float,
    mandate: dict,
    cap_pct: float | None = None,
) -> ToolResult:
    """Weight = max% × conviction ramp × vol scaling × correlation haircut, then optional cap."""
    max_w = mandate["max_single_name_pct"]
    ramp = min(1.0, max(0.0, (conviction - mandate["min_conviction"]) / 4))
    vol_scale = min(1.0, mandate["target_vol"] / realized_vol)
    corr_haircut = 1 - 0.5 * max(0.0, max_corr - mandate["corr_threshold"])
    weight = round(max_w * ramp * vol_scale * corr_haircut, 1)
    steps = f"{max_w:g}% × ramp {ramp:.2f} × vol {vol_scale:.2f} × corr {corr_haircut:.3f}"
    if cap_pct is not None and weight > cap_pct:
        weight = round(max(0.0, cap_pct), 1)
        steps += f" → capped at {weight:.1f}%"
    if nav is None:  # no fund yet: advise a share of the fund only
        data = {"weight_pct": weight, "shares": 0, "dollar_amount": 0.0}
        return _result("size_position", "computed", data, f"{steps} = {weight:.1f}% of your fund (shares once a fund is set)")
    shares = math.floor(weight / 100 * nav / limit_price) if weight > 0 else 0
    dollars = round(shares * limit_price, 2)
    data = {"weight_pct": weight, "shares": shares, "dollar_amount": dollars}
    evidence = f"{steps} = {weight:.1f}% NAV → {shares} sh ≈ ${dollars:,.0f}"
    return _result("size_position", "computed", data, evidence)
