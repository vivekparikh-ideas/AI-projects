"""Frozen data for evals (D-045): record every provider answer for a ticker once, then replay it.

A snapshot is plain JSON: `{"ticker", "as_of", "recorded_at", "recorded_from", "calls": {key: value}}`.
Keys name the provider method and its arguments, e.g. `insider|90` or `section|10-Q|risk_factors`.
A call that raised while recording is stored as `{"__error__": "..."}` and raises again on replay,
which is also how evals inject tool failures.

Replay never falls back to live data. A key that is missing raises `SnapshotMiss` and is logged in
`misses`: the research loop turns tool exceptions into "tool failed" messages for the agent, so the
eval harness reads `misses` to mark such a run INVALID instead of grading it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DAYS = (30, 90, 180)
FORMS = ("10-K", "10-Q")
SECTIONS = ("risk_factors", "mda")
QUARTERS = (1, 4)
SOURCE_KINDS = ("filings", "financials", "insider", "institutional", "dilution", "valuation", "price", "technicals")


class SnapshotMiss(LookupError):
    pass


def key(method: str, *args: Any) -> str:
    return "|".join([method, *("" if a is None else str(a) for a in args)])


def market_key(holdings: dict[str, float]) -> str:
    return key("market", json.dumps(dict(sorted(holdings.items())), separators=(",", ":")))


def all_calls(ticker: str) -> list[tuple[str, str, tuple]]:
    """Every (key, method, args) a research or no-fund PM run can ask the provider for."""
    calls = [
        (key("company"), "company", (ticker,)),
        (key("filings"), "filings", (ticker,)),
        *[(key("financials", q), "financials", (ticker, q)) for q in QUARTERS],
        *[(key("section", f, s), "section", (ticker, f, s)) for f in FORMS for s in SECTIONS],
        *[(key("insider", d), "insider", (ticker, d)) for d in DAYS],
        (key("institutional"), "institutional", (ticker,)),
        (key("dilution"), "dilution", (ticker,)),
        (key("valuation"), "valuation", (ticker,)),
        (key("price_history"), "price_history", (ticker,)),
        (key("technicals"), "technicals", (ticker,)),
        (market_key({}), "market", (ticker, {})),
        (key("quote"), "quote", (ticker,)),
        (key("close"), "close", (ticker,)),
        *[(key("source", k, None), "source", (k, ticker)) for k in SOURCE_KINDS],
        *[(key("source", "section", f), "source", ("section", ticker, f)) for f in FORMS],
    ]
    return calls


def record(source_provider: Any, ticker: str) -> dict[str, Any]:
    """Ask `source_provider` every question in `all_calls` and keep the answers (or the errors)."""
    ticker = ticker.upper()
    out: dict[str, Any] = {}
    for k, method, args in all_calls(ticker):
        try:
            value = getattr(source_provider, method)(*args)
            out[k] = list(value) if isinstance(value, tuple) else value
        except Exception as exc:  # a live failure is part of the frozen input
            out[k] = {"__error__": f"{type(exc).__name__}: {exc}"}
    return {
        "ticker": ticker,
        "as_of": source_provider.as_of(),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recorded_from": source_provider.name,
        "calls": out,
    }


def sha(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot["calls"], sort_keys=True, default=str).encode()).hexdigest()[:8]


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def save(snapshot: dict[str, Any], folder: str | Path) -> Path:
    path = Path(folder) / f"{snapshot['ticker']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=1, default=str, ensure_ascii=False))
    return path


class SnapshotProvider:
    """Replays one ticker's snapshot. Values are deep-copied so callers cannot change the snapshot."""

    name = "snapshot"

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.ticker = snapshot["ticker"]
        self.calls: dict[str, Any] = snapshot["calls"]
        self.misses: list[str] = []

    def _get(self, ticker: str, k: str) -> Any:
        if ticker.upper() != self.ticker or k not in self.calls:
            miss = f"{ticker.upper()} {k}"
            self.misses.append(miss)
            raise SnapshotMiss(f"not in snapshot: {miss}")
        value = self.calls[k]
        if isinstance(value, dict) and "__error__" in value:
            raise RuntimeError(value["__error__"])
        return copy.deepcopy(value)

    def as_of(self) -> str:
        return self.snapshot["as_of"]

    def company(self, ticker: str) -> str:
        return self._get(ticker, key("company"))

    def filings(self, ticker: str) -> list[dict[str, str]]:
        return self._get(ticker, key("filings"))

    def financials(self, ticker: str, quarters: int = 1) -> dict[str, Any]:
        return self._get(ticker, key("financials", quarters))

    def section(self, ticker: str, form: str, section: str) -> str:
        return self._get(ticker, key("section", form, section))

    def insider(self, ticker: str, days: int) -> dict[str, Any]:
        return self._get(ticker, key("insider", days))

    def institutional(self, ticker: str) -> dict[str, Any]:
        return self._get(ticker, key("institutional"))

    def dilution(self, ticker: str) -> dict[str, Any]:
        return self._get(ticker, key("dilution"))

    def valuation(self, ticker: str) -> dict[str, Any]:
        return self._get(ticker, key("valuation"))

    def price_history(self, ticker: str) -> dict[str, Any]:
        return self._get(ticker, key("price_history"))

    def technicals(self, ticker: str) -> dict[str, float]:
        return self._get(ticker, key("technicals"))

    def market(self, ticker: str, holdings: dict[str, float]) -> dict[str, Any]:
        return self._get(ticker, market_key(holdings))

    def quote(self, ticker: str) -> dict[str, float]:
        return self._get(ticker, key("quote"))

    def close(self, ticker: str) -> float:
        return self._get(ticker, key("close"))

    def source(self, kind: str, ticker: str, form: str | None = None) -> tuple[str, str | None]:
        label, url = self._get(ticker, key("source", kind, form))
        return label, url
