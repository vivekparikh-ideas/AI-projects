"""The user's fund: cash, holdings and a risk preset (D-021). No fund at all is a valid state."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from nexus.data import provider
from nexus.mock_data import MANDATE
from nexus.schemas import PortfolioSnapshot, Position, TaxLot

Preset = Literal["careful", "balanced", "bold"]

# Each preset overrides the single-name and worst-day-loss limits; everything else stays as MANDATE.
PRESETS: dict[str, dict[str, float]] = {
    "careful": {"max_single_name_pct": 3.0, "max_var_pct": 1.5},
    "balanced": {"max_single_name_pct": 5.0, "max_var_pct": 2.5},
    "bold": {"max_single_name_pct": 8.0, "max_var_pct": 4.0},
}
DEFAULT_VOL = 0.35  # used for holdings without market data (M1 fixtures only cover a few tickers)
HOLDING_CORR = 0.6  # assumed pairwise correlation between holdings for the starting VaR


def mandate_for(preset: str, overrides: dict[str, float] | None = None) -> dict[str, float]:
    return {**MANDATE, **PRESETS[preset], **(overrides or {})}


class Holding(BaseModel):
    ticker: str
    shares: float = Field(gt=0)
    cost_basis: float = Field(gt=0)
    acquired: str = ""  # defaults to the provider's date


class FundConfig(BaseModel):
    cash: float = Field(ge=0)
    holdings: list[Holding] = []
    preset: Preset = "balanced"
    mandate_overrides: dict[str, float] = {}

    @property
    def mandate(self) -> dict[str, float]:
        return mandate_for(self.preset, self.mandate_overrides)

    def snapshot(self) -> PortfolioSnapshot:
        """Mark holdings to the latest known price (fixture close, else cost basis) and build the ledger view."""
        priced = [(h, _price(h.ticker, h.cost_basis)) for h in self.holdings]
        today = provider().as_of()
        nav = self.cash + sum(h.shares * px for h, px in priced)
        positions = [Position(ticker=h.ticker, shares=h.shares, price=px, weight_pct=round(h.shares * px / nav * 100, 2)) for h, px in priced]
        lots = [
            TaxLot(lot_id=f"{h.ticker}-{h.acquired or today}-setup", ticker=h.ticker, shares=int(h.shares), cost_basis=h.cost_basis, acquired=h.acquired or today, term="short_term")
            for h in self.holdings
        ]
        return PortfolioSnapshot(
            as_of=today, nav=round(nav, 2), settled_cash=self.cash, beta=_beta(positions),
            current_var_pct=_starting_var(positions), positions=positions, tax_lots=lots,
        )


def _price(ticker: str, fallback: float) -> float:
    try:
        return provider().close(ticker)
    except Exception:  # unknown to the provider (e.g. fixtures cover few tickers): use cost basis
        return fallback


def _market(ticker: str) -> dict:
    try:
        return provider().market(ticker, {})
    except Exception:
        return {"realized_vol": DEFAULT_VOL, "beta": 1.0}


def _vol(ticker: str) -> float:
    return _market(ticker)["realized_vol"]


def _beta(positions: list[Position]) -> float:
    invested = sum(p.weight_pct for p in positions) / 100
    if not invested:
        return 0.0
    weighted = sum(p.weight_pct / 100 * _market(p.ticker)["beta"] for p in positions)
    return round(weighted, 2)


def _starting_var(positions: list[Position]) -> float:
    """Parametric 99% 1-day VaR of the holdings, assuming one pairwise correlation (M3 uses real history)."""
    from nexus.tools.risk import TRADING_DAYS, Z_99

    legs = [p.weight_pct / 100 * _vol(p.ticker) / math.sqrt(TRADING_DAYS) for p in positions]
    variance = sum(a * b * (1.0 if i == j else HOLDING_CORR) for i, a in enumerate(legs) for j, b in enumerate(legs))
    return round(Z_99 * math.sqrt(variance) * 100, 2)


def load_fund(path: str | Path) -> FundConfig:
    return FundConfig(**yaml.safe_load(Path(path).read_text()))


def save_fund(fund: FundConfig, path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(fund.model_dump(), sort_keys=False))
