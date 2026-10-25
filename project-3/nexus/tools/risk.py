"""Risk Gate checks: pure deterministic math, no LLM (D-002)."""

from __future__ import annotations

import math
from datetime import date

from nexus.schemas import RealizedLoss, RuleResult

Z_99 = 2.326  # one-tailed 99% normal quantile
TRADING_DAYS = 252


def check_concentration(ticker: str, existing_pct: float, add_pct: float, limit_pct: float) -> RuleResult:
    post = round(existing_pct + add_pct, 2)
    ok = post <= limit_pct
    detail = f"{post:.2f}% of NAV after trade (holds {existing_pct:.2f}%) {'≤' if ok else '>'} {limit_pct:g}%"
    return RuleResult(name="concentration", passed=ok, observed=post, limit=limit_pct, unit="% NAV", resizable=True, detail=detail)


def check_cash_and_margin(dollar_amount: float, settled_cash: float) -> RuleResult:
    ok = dollar_amount <= settled_cash
    detail = f"Need ${dollar_amount:,.0f} {'≤' if ok else '>'} settled cash ${settled_cash:,.0f} (no margin)"
    return RuleResult(name="cash_and_margin", passed=ok, observed=round(dollar_amount, 2), limit=settled_cash, unit="USD", resizable=True, detail=detail)


def check_wash_sale(ticker: str, realized_losses: list[RealizedLoss], as_of: str, window_days: int) -> RuleResult:
    today = date.fromisoformat(as_of)
    hits = [
        loss for loss in realized_losses
        if loss.ticker == ticker and 0 <= (today - date.fromisoformat(loss.date)).days <= window_days
    ]
    if hits:
        days = (today - date.fromisoformat(hits[0].date)).days
        detail = f"{len(hits)} realized loss on {ticker} {days} days ago (${abs(hits[0].amount_usd):,.0f} loss) within {window_days}-day window"
    else:
        detail = f"0 realized losses on {ticker} in trailing {window_days} days"
    return RuleResult(name="wash_sale", passed=not hits, observed=len(hits), limit=0, unit="collisions", resizable=False, detail=detail)


def var_headroom_pct(var_before_pct: float, limit_pct: float, realized_vol: float, corr_to_portfolio: float) -> float:
    """Largest addition (% of NAV) that keeps 99% 1-day VaR at or under the limit; 0 when there is no room.

    Inverts compute_marginal_var: with p the position's own VaR, VaR_after² = v² + p² + 2ρvp ≤ L².
    """
    v, L, rho = var_before_pct, limit_pct, corr_to_portfolio
    if L <= v:
        return 0.0
    p_max = -rho * v + math.sqrt(max(0.0, rho * rho * v * v - v * v + L * L))
    daily_vol = realized_vol / math.sqrt(TRADING_DAYS)
    return max(0.0, p_max / (Z_99 * daily_vol)) if daily_vol else 0.0


def compute_marginal_var(ticker: str, add_pct: float, var_before_pct: float, limit_pct: float, realized_vol: float, corr_to_portfolio: float) -> RuleResult:
    """Parametric 99% 1-day VaR after adding the position, using its correlation to the portfolio."""
    daily_vol = realized_vol / math.sqrt(TRADING_DAYS)
    pos_var = Z_99 * (add_pct / 100) * daily_vol * 100  # in % of NAV
    after = math.sqrt(var_before_pct**2 + pos_var**2 + 2 * corr_to_portfolio * var_before_pct * pos_var)
    after = round(after, 2)
    ok = after <= limit_pct
    detail = f"99% 1-day VaR {var_before_pct:.2f}% → {after:.2f}% of NAV {'≤' if ok else '>'} {limit_pct:g}%"
    return RuleResult(name="marginal_var", passed=ok, observed=after, limit=limit_pct, unit="% NAV", resizable=True, detail=detail)
