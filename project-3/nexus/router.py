"""Journey router: a deterministic command parser, never an LLM (D-023, R-ARCH-4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

JourneyKind = Literal["evaluate", "research", "whatif", "monitor", "scan"]
LATER = {"monitor": "Position monitoring arrives in Milestone 3.", "scan": "Watchlist scans arrive in Milestone 4."}

_TICKER = r"\$?([A-Za-z]{1,5}(?:\.[A-Za-z])?)"
_AMOUNT = r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?"


@dataclass(frozen=True)
class Journey:
    kind: JourneyKind
    ticker: str = ""
    amount: float | None = None


class UnknownCommand(ValueError):
    pass


def _money(number: str, suffix: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * {"k": 1e3, "m": 1e6}.get((suffix or "").lower(), 1)


def parse(text: str) -> Journey:
    t = " ".join(text.strip().split())
    if m := re.fullmatch(rf"(?:can i add|what if i (?:add|buy)|what if)\s+{_AMOUNT}\s+(?:of|in|worth of)\s+{_TICKER}\??", t, re.I):
        return Journey("whatif", m.group(3).upper(), _money(m.group(1), m.group(2)))
    if m := re.fullmatch(rf"research\s+{_TICKER}", t, re.I):
        return Journey("research", m.group(1).upper())
    if re.fullmatch(r"(?:check|monitor)\s+(?:my\s+)?(?:stocks|holdings|positions)", t, re.I):
        return Journey("monitor")
    if re.fullmatch(r"scan(?:\s+(?:my\s+)?watchlist)?", t, re.I):
        return Journey("scan")
    if m := re.fullmatch(rf"(?:evaluate|analy[sz]e|should i buy)\s+{_TICKER}\??", t, re.I):
        return Journey("evaluate", m.group(1).upper())
    if m := re.fullmatch(_TICKER, t):
        return Journey("evaluate", m.group(1).upper())
    raise UnknownCommand(
        f"Not sure what to do with {text!r}. Try: Evaluate NVDA · Research TSLA · Can I add $50k of AMD? · Check my stocks"
    )
