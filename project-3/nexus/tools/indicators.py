"""Pure technical-indicator and return math (no I/O), shared by the live data provider."""

from __future__ import annotations

import math
from statistics import fmean, pstdev

TRADING_DAYS = 252


def sma(values: list[float], n: int) -> float:
    window = values[-n:]
    return fmean(window) if window else float("nan")


def rsi_wilder(closes: list[float], n: int = 14) -> float:
    """Wilder's RSI: smoothed average gain / loss over n periods."""
    if len(closes) <= n:
        return float("nan")
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain, avg_loss = fmean(gains[:n]), fmean(losses[:n])
    for g, l in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + l) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], n: int = 20) -> float:
    """Volume-weighted typical price over the last n daily bars."""
    rows = list(zip(highs, lows, closes, volumes))[-n:]
    vol = sum(v for *_, v in rows)
    return sum((h + l + c) / 3 * v for h, l, c, v in rows) / vol if vol else float("nan")


def returns(closes: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(closes, closes[1:]) if a]


def annualized_vol(rets: list[float]) -> float:
    return pstdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) > 1 else 0.0


def correlation(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    x, y = x[-n:], y[-n:]
    mx, my = fmean(x), fmean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return cov / (sx * sy) if sx and sy else 0.0


def beta(asset: list[float], market: list[float]) -> float:
    n = min(len(asset), len(market))
    if n < 3:
        return 1.0
    a, m = asset[-n:], market[-n:]
    ma, mm = fmean(a), fmean(m)
    var_m = sum((x - mm) ** 2 for x in m)
    return sum((x - ma) * (y - mm) for x, y in zip(a, m)) / var_m if var_m else 1.0
