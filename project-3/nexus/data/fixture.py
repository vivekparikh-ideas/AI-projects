"""The M1 sample data behind the provider interface. No network; used by every test."""

from __future__ import annotations

from typing import Any

from nexus.mock_data import AS_OF, FILINGS, ticker_data


class FixtureProvider:
    name = "fixture"

    def as_of(self) -> str:
        return AS_OF

    def company(self, ticker: str) -> str:
        return ticker_data(ticker)["company"]

    def filings(self, ticker: str) -> list[dict[str, str]]:
        return FILINGS[ticker]

    def financials(self, ticker: str, quarters: int = 1) -> dict[str, Any]:
        return dict(ticker_data(ticker)["financials"])

    def section(self, ticker: str, form: str, section: str) -> str:
        return ticker_data(ticker)["sections"][section]

    def insider(self, ticker: str, days: int) -> dict[str, Any]:
        return dict(ticker_data(ticker)["insider"])

    def institutional(self, ticker: str) -> dict[str, Any]:
        return dict(ticker_data(ticker)["institutional"])

    def dilution(self, ticker: str) -> dict[str, Any]:
        return dict(ticker_data(ticker)["dilution"])

    def valuation(self, ticker: str) -> dict[str, Any]:
        return dict(ticker_data(ticker)["valuation"])

    def price_history(self, ticker: str) -> dict[str, Any]:
        return {"bars": 252, "last_close": ticker_data(ticker)["technicals"]["spot"]}

    def technicals(self, ticker: str) -> dict[str, float]:
        return dict(ticker_data(ticker)["technicals"])

    def market(self, ticker: str, holdings: dict[str, float]) -> dict[str, Any]:
        """Overlap counts only stocks the fund holds (D-027)."""
        mk = ticker_data(ticker)["market"]
        held = mk["max_corr_holding"] in holdings
        return {
            "realized_vol": mk["realized_vol"],
            "beta": mk["beta"],
            "max_corr_holding": mk["max_corr_holding"] if held else None,
            "max_corr": mk["max_corr"] if held else 0.0,
            "corr_to_portfolio": mk["corr_to_portfolio"] if holdings else 0.0,
        }

    def quote(self, ticker: str) -> dict[str, float]:
        return dict(ticker_data(ticker)["quote"])

    def close(self, ticker: str) -> float:
        return ticker_data(ticker)["close"]

    def source(self, kind: str, ticker: str, form: str | None = None) -> tuple[str, str | None]:
        return "sample data", None
