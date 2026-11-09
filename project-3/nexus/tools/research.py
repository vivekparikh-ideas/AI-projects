"""Research Analyst tools R1–R11 + submit_dossier (REQUIREMENTS §5).

M1: data comes from fixtures; signatures match what M2 implements against SEC EDGAR and yfinance.
compute_scorecard and the grounding check are real logic from M1.
"""

from __future__ import annotations

import json
import re
from typing import Any

from nexus.data import provider
from nexus.schemas import (
    AgentStep,
    Dilution,
    ResearchDossier,
    Scorecard,
    Source,
    Technicals,
    ToolResult,
    Valuation,
)


def _result(tool: str, source: str, data: dict[str, Any], evidence: str, origin: tuple[str, str | None] | None = None) -> ToolResult:
    label, url = origin or (None, None)
    return ToolResult(tool=tool, source=f"{provider().name}:{source}", as_of=provider().as_of(), data=data, evidence=evidence, source_label=label, source_url=url)


def _signed(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"+{x:g}" if x > 0 else f"−{abs(x):g}" if x < 0 else "0"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f}%"


def _usd_b(x: float | None) -> str:
    return "n/a" if x is None else f"${x:g}B"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f}"


# R1
def sec_list_filings(ticker: str) -> ToolResult:
    filings = provider().filings(ticker)
    evidence = " | ".join(f"{f['form']} {f['date']}" for f in filings) or "No recent filings"
    return _result("sec_list_filings", "sec_edgar", {"filings": filings}, evidence, provider().source("filings", ticker))


# R2
def sec_get_financials(ticker: str, quarters: int = 1) -> ToolResult:
    f = provider().financials(ticker, quarters)
    data = {k: v for k, v in f.items() if k != "gross_margin_4q"}
    evidence = (
        f"Rev ${f['revenue_q_usd_b']:g}B ({_signed(f['revenue_growth_pct'])}% YoY) | "
        f"Gross margin {_pct(f['gross_margin_pct'])} | SBC {_pct(f['sbc_pct_rev'])} of rev | "
        f"net shares {_signed(f['net_share_change_pct'])}% YoY"
    )
    if f.get("operating_cash_flow_usd_b") is not None:
        evidence += (
            f" | {f['cash_flow_year']} operating cash flow {_usd_b(f['operating_cash_flow_usd_b'])} vs net income "
            f"{_usd_b(f.get('net_income_usd_b'))} | receivables {_signed(f.get('receivables_growth_pct'))}% YoY"
        )
    if quarters > 1:
        trend = f["gross_margin_4q"][-quarters:]
        data["gross_margin_trend"] = trend
        evidence = "Gross margin " + " → ".join(f"{x:.1f}%" for x in trend) + f" (last {len(trend)} quarters)"
    return _result("sec_get_financials", "sec_edgar_xbrl", data, evidence, provider().source("financials", ticker))


# R3
def sec_get_filing_section(ticker: str, form: str = "10-Q", section: str = "risk_factors") -> ToolResult:
    text = provider().section(ticker, form, section)
    evidence = text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + "…"
    return _result("sec_get_filing_section", f"sec_edgar:{form}", {"form": form, "section": section, "text": text}, evidence, provider().source("section", ticker, form))


# R4
def sec_get_insider_trades(ticker: str, days: int = 90) -> ToolResult:
    ins = provider().insider(ticker, days)
    return _result("sec_get_insider_trades", "sec_edgar_form4", {"days": days, **ins}, ins["summary"], provider().source("insider", ticker))


# R5
def get_institutional_holders(ticker: str) -> ToolResult:
    inst = provider().institutional(ticker)
    return _result("get_institutional_holders", "holders", inst, inst["summary"], provider().source("institutional", ticker))


# R6
def get_cap_table(ticker: str) -> ToolResult:
    d = provider().dilution(ticker)
    shares = "n/a" if d["diluted_shares_b"] is None else f"{d['diluted_shares_b']:g}B"
    evidence = (
        f"{shares} diluted shares | SBC {_pct(d['sbc_pct_rev'])} of rev | "
        f"${d['buyback_usd_b'] or 0:g}B buyback | net shares {_signed(d['net_share_change_pct'])}% YoY"
    )
    return _result("get_cap_table", "sec_edgar_xbrl", d, evidence, provider().source("dilution", ticker))


# R7
def get_valuation(ticker: str) -> ToolResult:
    v = provider().valuation(ticker)
    evidence = f"Fwd P/E {_num(v['fwd_pe'])} | EV/EBITDA {_num(v['ev_ebitda'])} | FCF yield {_pct(v['fcf_yield_pct'])}"
    return _result("get_valuation", "market_data", v, evidence, provider().source("valuation", ticker))


# R8
def get_price_history(ticker: str, period: str = "1y") -> ToolResult:
    h = provider().price_history(ticker)
    return _result("get_price_history", "market_data", {"period": period, **h}, f"{h['bars']} daily bars | last close ${h['last_close']:.2f}", provider().source("price", ticker))


# R9
def compute_technicals(ticker: str) -> ToolResult:
    t = provider().technicals(ticker)
    evidence = (
        f"Spot ${t['spot']:.2f} | 50-DMA ${t['dma50']:.2f} | 200-DMA ${t['dma200']:.2f} | "
        f"RSI {t['rsi14']:.1f} | VWAP ${t['vwap']:.2f}"
    )
    return _result("compute_technicals", "computed", t, evidence, provider().source("technicals", ticker))


# R10
def get_earnings_transcript(ticker: str) -> ToolResult:
    return _result("get_earnings_transcript", "unavailable", {}, "Not available: no transcript API key (optional tool)")


# R11
def _clamp(x: float) -> float:
    return max(0.0, min(10.0, x))


NEUTRAL = 5.0  # a component whose input is missing scores neutral instead of guessing


def compute_scorecard(financials: dict[str, Any], valuation: dict[str, Any], technicals: dict[str, Any]) -> ToolResult:
    """Deterministic base score (D-016): growth 30%, trend 25%, valuation 20%, dilution 25%."""
    g, pe, ns = financials.get("revenue_growth_pct"), valuation.get("fwd_pe"), financials.get("net_share_change_pct")
    growth = _clamp(g / 10) if g is not None else NEUTRAL
    t = technicals
    trend = 4 * (t["spot"] > t["dma200"]) + 3 * (t["spot"] > t["dma50"]) + 3 * (40 <= t["rsi14"] <= 70)
    value = _clamp(10 - 0.35 * (pe - 15)) if pe is not None and pe > 0 else NEUTRAL
    dilution = _clamp(6 - 5 * ns) if ns is not None else NEUTRAL
    base = round(0.30 * growth + 0.25 * trend + 0.20 * value + 0.25 * dilution, 1)
    missing = [n for n, v in (("growth", g), ("valuation", pe), ("dilution", ns)) if v is None]
    data = {"growth": round(growth, 2), "trend": float(trend), "valuation": round(value, 2), "dilution": round(dilution, 2), "base_score": base}
    evidence = f"Base score {base:.1f} (growth {growth:.1f} · trend {trend:.1f} · value {value:.1f} · dilution {dilution:.1f})"
    if missing:
        evidence += " | neutral for missing " + ", ".join(missing)
    return _result("compute_scorecard", "computed", data, evidence)


# submit_dossier: the agent's finishing action
class GroundingError(ValueError):
    pass


_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(n) for n in _NUM.findall(text)}


def check_grounding(claims: list[str], sources: list[ToolResult]) -> None:
    """Every number the LLM writes must appear in some tool output (D-012)."""
    known: set[float] = set()
    for r in sources:
        known |= _numbers(r.evidence) | _numbers(json.dumps(r.data))
    missing = sorted({n for c in claims for n in _numbers(c)} - known)
    if missing:
        raise GroundingError(f"numbers not found in any tool output: {', '.join(f'{m:g}' for m in missing)}")


def conviction_from(base_score: float, adjustment: float) -> float:
    """Base score + Ava's adjustment, kept inside 0–10 (D-046): a low base can't make conviction negative."""
    return round(min(10.0, max(0.0, base_score + adjustment)), 1)


def submit_dossier(
    ticker: str,
    results: dict[str, ToolResult],
    synthesis: dict[str, Any],
    trace: list[AgentStep],
    previous: ResearchDossier | None = None,
) -> ResearchDossier:
    notes = list(previous.notes) if previous else []
    if synthesis.get("note"):
        notes.append(synthesis["note"])
    claims = [synthesis["bull_case"], synthesis["bear_case"], synthesis["adjustment_reason"], *notes]
    check_grounding(claims, list(results.values()))

    if previous is not None:
        return previous.model_copy(update={"notes": notes, "agent_trace": [*previous.agent_trace, *trace]})

    fin = results["sec_get_financials"].data
    card = Scorecard(**results["compute_scorecard"].data)
    cap = results.get("get_cap_table")
    insider = results.get("sec_get_insider_trades")
    inst = results.get("get_institutional_holders")
    adj = synthesis["llm_adjustment"]
    sources, seen = [], set()
    for r in results.values():
        if r.source_label and (r.source_label, r.source_url) not in seen:
            seen.add((r.source_label, r.source_url))
            sources.append(Source(tool=r.tool, label=r.source_label, url=r.source_url))
    sec_docs = sum(1 for s in sources if s.label.startswith(("10-", "8-", "SEC")))
    filings_checked = insider.data.get("filings_checked") if insider else None
    bars = results["get_price_history"].data.get("bars") if "get_price_history" in results else None
    parts = [f"{sec_docs} SEC source{'s' if sec_docs != 1 else ''}"]
    if filings_checked:
        parts.append(f"{filings_checked} insider filings")
    if bars:
        parts.append(f"{bars} days of prices")
    parts.append(f"{len(trace)} follow-up check{'s' if len(trace) != 1 else ''}")
    return ResearchDossier(
        sources=sources,
        reading_summary=" · ".join(parts),
        ticker=ticker,
        bull_case=synthesis["bull_case"],
        bear_case=synthesis["bear_case"],
        valuation=Valuation(**results["get_valuation"].data),
        dilution=Dilution(**(cap.data if cap else provider().dilution(ticker))),
        technicals=Technicals(**results["compute_technicals"].data),
        revenue_growth_pct=fin["revenue_growth_pct"],
        gross_margin_pct=fin["gross_margin_pct"],
        insider_summary=insider.evidence if insider else "Not checked",
        institutional_summary=inst.evidence if inst else "Not checked",
        notes=notes,
        scorecard=card,
        llm_adjustment=adj,
        adjustment_reason=synthesis["adjustment_reason"],
        conviction_score=conviction_from(card.base_score, adj),
        agent_trace=trace,
    )
