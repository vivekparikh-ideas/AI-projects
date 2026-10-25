"""Plain-English explanations (D-007). Display-only: no downstream role reads these.

Deterministic templates for every role in M1; percentages and basis points become dollars.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from nexus.schemas import (
    ExecutionReceipt,
    LedgerUpdate,
    PlainEnglish,
    Recommendation,
    ResearchDossier,
    RiskCheckResult,
    RuleResult,
    TradeIntent,
)

GLOSSARY: dict[str, str] = yaml.safe_load((Path(__file__).parent / "glossary.yaml").read_text())

_RULE_PLAIN = {
    "concentration": "too much of the fund would sit in one stock",
    "cash_and_margin": "there isn't enough settled cash",
    "wash_sale": "we sold this stock at a loss recently, so buying now breaks the tax wash-sale rule",
    "marginal_var": "the fund's worst-day loss would get too large",
}


def conviction_label(score: float) -> str:
    if score >= 8:
        return "a strong buy"
    if score >= 6.5:
        return "a buy"
    if score >= 5:
        return "a borderline buy"
    return "unattractive"


def research(d: ResearchDossier) -> PlainEnglish:
    trend = "above" if d.technicals.spot > d.technicals.dma200 else "below"
    return PlainEnglish(
        headline=f"{d.ticker} looks like {conviction_label(d.conviction_score)} ({d.conviction_score:.1f} out of 10).",
        what_it_means=(
            f"Sales grew {d.revenue_growth_pct:g}% in a year and the price is {trend} its long-term average. "
            f"Our formula scored the business {d.scorecard.base_score:.1f}; the analyst moved it {d.llm_adjustment:+.1f} "
            f"because: {d.adjustment_reason[0].lower()}{d.adjustment_reason[1:]}"
        ),
        so_what="Next, the Portfolio Manager decides whether to buy and how much.",
    )


def pm_question(ticker: str, question: str) -> PlainEnglish:
    return PlainEnglish(
        headline=f"The Portfolio Manager needs one more answer before deciding on {ticker}.",
        what_it_means=f'It asked the Research Analyst: "{question}"',
        so_what="Research runs once more, then the Portfolio Manager decides.",
    )


def pm_recommendation(r: Recommendation) -> PlainEnglish:
    verb = "Put" if r.action == "BUY" else "Take"
    return PlainEnglish(
        headline=f"{verb} about {r.target_weight_pct:.1f}% of your fund {'into' if r.action == 'BUY' else 'out of'} {r.ticker}.",
        what_it_means=f"Pay no more than ${r.limit_price:,.2f} a share, and sell if it falls about {r.stop_loss_pct:.1f}% below that.",
        so_what="To turn this into shares and run the safety checks, The Vault needs to know how much cash you want to work with.",
    )


def pm(intent: TradeIntent, nav: float, resized: bool = False) -> PlainEnglish:
    if intent.action == "HOLD":
        return PlainEnglish(
            headline=f"Don't trade {intent.ticker} right now.",
            what_it_means=intent.rationale or "The case isn't strong enough to risk money.",
            so_what="The run ends here; nothing is bought or sold.",
        )
    verb = "Put" if intent.action == "BUY" else "Take"
    return PlainEnglish(
        headline=(
            f"{'Resized: ' if resized else ''}{verb} about ${intent.dollar_amount / 1000:,.0f}k "
            f"({intent.target_weight_pct:.1f}% of the fund) {'into' if intent.action == 'BUY' else 'out of'} {intent.ticker}."
        ),
        what_it_means=(
            f"That is {intent.shares} shares at no more than ${intent.limit_price:,.2f} each. "
            f"If the price falls to ${intent.stop_loss_price:,.2f}, we sell to cap the loss."
        ),
        so_what="Next, The Vault checks this against your safety rules.",
    )


def risk(r: RiskCheckResult, nav: float, route: str) -> PlainEnglish:
    failed: list[RuleResult] = [x for x in r.rules if not x.passed]
    if route == "whatif":
        if r.approved:
            return PlainEnglish(
                headline="Yes, that trade would pass all the safety checks.",
                what_it_means=f"On a very bad day (the worst 1 in 100) the fund would likely lose no more than about ${r.var_after_pct / 100 * nav:,.0f}.",
                so_what="This was only a check; nothing was bought. Evaluate the stock to get a real recommendation.",
            )
        return PlainEnglish(
            headline="No, that trade would be blocked.",
            what_it_means="The problem: " + "; ".join(_RULE_PLAIN[x.name] for x in failed) + ".",
            so_what="This was only a check; nothing was bought.",
        )
    if r.approved:
        var_rule = next(x for x in r.rules if x.name == "marginal_var")
        return PlainEnglish(
            headline=f"All {len(r.rules)} safety checks passed.",
            what_it_means=(
                f"On a very bad day (the worst 1 in 100), the fund would likely lose no more than about "
                f"${r.var_after_pct / 100 * nav:,.0f}, under our ${var_rule.limit / 100 * nav:,.0f} limit."
            ),
            so_what="Next, you approve or reject the trade. If you approve, it is simulated at live prices; nothing real is bought.",
        )
    reasons = "; ".join(_RULE_PLAIN[x.name] for x in failed)
    if route == "revise":
        return PlainEnglish(
            headline="Trade is too big for the rules, sending it back to be resized.",
            what_it_means=f"The problem: {reasons}.",
            so_what="The Portfolio Manager gets one chance to shrink the trade.",
        )
    return PlainEnglish(
        headline="Trade blocked by the safety rules.",
        what_it_means=f"The problem: {reasons}.",
        so_what="The run ends here; nothing is bought.",
    )


def execution(x: ExecutionReceipt) -> PlainEnglish:
    better = x.slippage_bps <= 0
    return PlainEnglish(
        headline=f"Simulated buying all {x.shares_filled} {x.ticker} shares in {len(x.slices)} small orders." if x.fill_pct == 100 else f"Simulated buying {x.shares_filled} of {x.shares_requested} {x.ticker} shares.",
        what_it_means=(
            f"At live prices this would have cost ${x.avg_fill_price:,.3f} a share on average, {abs(x.slippage_bps) / 100:.3f}% "
            f"{'less' if better else 'more'} than the ${x.arrival_price:,.2f} market price when it started. No real order was placed."
        ),
        so_what="Next, Penny adds the simulated purchase to your portfolio.",
    )


def ledger(u: LedgerUpdate) -> PlainEnglish:
    return PlainEnglish(
        headline="Your portfolio is updated with the simulated trade." if u.reconciled else "Your portfolio records don't add up; new simulated trades are paused.",
        what_it_means=f"It is now worth ${u.nav_after:,.2f}, with ${u.cash_after:,.2f} cash left.",
        so_what="To act on this for real, place the order yourself in your own brokerage app.",
    )
