"""Market and filings data behind one interface (D-030).

`fixture` serves the M1 sample data (tests, no network); `live` serves SEC EDGAR + yfinance;
`snapshot` (`nexus/data/snapshot.py`) replays a recorded ticker for evals, installed with `set_provider()`.
Tools call `provider()`; the CLI picks the provider once per process with `use()`.
"""

from __future__ import annotations

from typing import Any, Protocol


class DataProvider(Protocol):
    name: str

    def as_of(self) -> str: ...
    def company(self, ticker: str) -> str: ...
    def filings(self, ticker: str) -> list[dict[str, str]]: ...
    def financials(self, ticker: str, quarters: int = 1) -> dict[str, Any]: ...
    def section(self, ticker: str, form: str, section: str) -> str: ...
    def insider(self, ticker: str, days: int) -> dict[str, Any]: ...
    def institutional(self, ticker: str) -> dict[str, Any]: ...
    def dilution(self, ticker: str) -> dict[str, Any]: ...
    def valuation(self, ticker: str) -> dict[str, Any]: ...
    def price_history(self, ticker: str) -> dict[str, Any]: ...
    def technicals(self, ticker: str) -> dict[str, float]: ...
    def market(self, ticker: str, holdings: dict[str, float]) -> dict[str, Any]: ...
    def quote(self, ticker: str) -> dict[str, float]: ...
    def close(self, ticker: str) -> float: ...
    def source(self, kind: str, ticker: str, form: str | None = None) -> tuple[str, str | None]: ...  # (label, url)


_current: DataProvider | None = None


def use(name: str) -> DataProvider:
    global _current
    if name == "fixture":
        from nexus.data.fixture import FixtureProvider

        _current = FixtureProvider()
    elif name == "live":
        from nexus.data.live import LiveProvider

        _current = LiveProvider()
    else:
        raise ValueError(f"unknown data provider {name!r} (fixture | live)")
    return _current


def set_provider(p: DataProvider) -> DataProvider:
    """Install a provider object directly; evals use it for a `SnapshotProvider` per case (D-045)."""
    global _current
    _current = p
    return _current


def provider() -> DataProvider:
    return _current or use("fixture")
