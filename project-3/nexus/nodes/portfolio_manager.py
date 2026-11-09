"""Node 2 — Portfolio Manager: LLM picks the action; the P5 formula sets the size (D-006, D-018).

Without a fund the PM still advises, as a share of the fund (`Recommendation`, D-021).
"""

from __future__ import annotations

from typing import Any

from nexus import explain
from nexus.data import provider
from nexus.nodes.research_analyst import _llm_fields
from nexus.policies import make_pm_policy
from nexus.schemas import HandoffSummary, Recommendation, TradeIntent
from nexus.state import MAX_RESEARCH_ROUNDS, FundGraphState
from nexus.telemetry import clip, emit_agent_started, micro_action, now_iso, record_handoff, ref
from nexus.tools import registry
from nexus.tools.risk import var_headroom_pct

AGENT = "portfolio_manager"


def _reuse_prices(state: FundGraphState) -> dict[str, Any] | None:
    """A Risk Gate resize reuses the last intent's prices; a resume after fund setup reuses the advice (D-031)."""
    if state.risk_feedback and state.intent and state.intent.action != "HOLD":
        i = state.intent
        return {"action": i.action, "limit_price": i.limit_price, "stop_loss_price": i.stop_loss_price, "rationale": i.rationale}
    if state.recommendation and state.portfolio is not None and state.recommendation.action != "HOLD":
        r = state.recommendation
        return {"action": r.action, "limit_price": r.limit_price, "stop_loss_price": r.stop_loss_price, "rationale": r.rationale}
    return None


def _revision_cap(feedback, snap, mandate, ticker: str, vol: float, corr: dict) -> tuple[float, str]:
    """Largest weight (% NAV) that clears every failed resizable rule, and why none exists when it is 0 (D-041)."""
    caps: list[float] = []
    reasons: list[str] = []
    names = {r.name for r in feedback}
    if "concentration" in names:
        held = snap.weight_of(ticker)
        caps.append(mandate["max_single_name_pct"] - held - mandate["resize_buffer_pct"])
        reasons.append(f"you already hold {held:.1f}% in {ticker}, against a {mandate['max_single_name_pct']:g}% limit")
    if "cash_and_margin" in names:
        caps.append(snap.settled_cash / snap.nav * 100 * 0.98)
        reasons.append(f"only ${snap.settled_cash:,.0f} of cash is available")
    if "marginal_var" in names:
        target = mandate["max_var_pct"] - 0.05  # aim just inside the limit so rounding can't tip it over
        caps.append(var_headroom_pct(snap.current_var_pct, target, vol, corr.get("corr_to_portfolio", 0.0)))
        reasons.append(f"the portfolio's worst-day loss is already {snap.current_var_pct:.2f}% before this trade, against a {mandate['max_var_pct']:g}% limit")
    cap = min(caps) if caps else 0.0
    return cap, "No room to add under the safety rules: " + "; ".join(reasons) + "."


def apply_buy_floor(decision: dict[str, Any], conviction: float, floor: float) -> tuple[dict[str, Any], bool]:
    """Code, not the model, has the final say on the BUY floor (D-034). Returns (decision, converted)."""
    if decision["action"] == "BUY" and conviction < floor:
        return {"action": "HOLD", "rationale": f"Conviction {conviction:.1f} is below the {floor:g} buy floor."}, True
    return decision, False


def _hold(ticker: str, why: str) -> TradeIntent:
    return TradeIntent(action="HOLD", ticker=ticker, target_weight_pct=0, dollar_amount=0, shares=0, limit_price=0, stop_loss_price=0, rationale=why)


def portfolio_manager(state: FundGraphState) -> dict[str, Any]:
    run, ticker, snap = state.run_id, state.ticker, state.portfolio
    attempt = state.pm_attempts + 1
    started = now_iso()
    feedback = state.risk_feedback
    note = "revision: Risk Gate failed " + ", ".join(r.name for r in feedback) if feedback else ""
    emit_agent_started(run, AGENT, note)
    seq = len(state.handoff_log) + 1
    consumed = [ref("portfolio_ledger", snap)] if snap else []
    if state.dossier is not None:
        consumed.insert(0, ref("research_analyst", state.dossier))
    if feedback and state.risk is not None:
        consumed.append(ref("risk_gate", state.risk))
    base = {"pm_attempts": attempt, "risk_feedback": None}

    if state.dossier is None:
        intent = _hold(ticker, "Research could not produce a validated dossier.")
        return {**base, **_finish(state, seq, started, consumed, intent, "hold")}

    d = state.dossier
    if snap:
        registry.use(run, AGENT, "get_portfolio_snapshot", snapshot=snap)
    mandate = registry.use(run, AGENT, "get_fund_mandate", mandate=state.mandate).data
    holdings = {p.ticker: p.weight_pct for p in snap.positions} if snap else {}
    corr = registry.use(run, AGENT, "compute_correlation_beta", ticker=ticker, holdings=holdings).data
    vol = registry.use(run, AGENT, "compute_realized_vol", ticker=ticker).data["realized_vol"]

    policy = make_pm_policy(ticker, state.fixture)
    reuse = _reuse_prices(state)
    label = "Re-sizing with your fund" if reuse and not feedback else "Re-deciding after Risk Gate feedback" if feedback else "Deciding action (LLM)"
    with micro_action(run, AGENT, "pm_decide", label) as ev:
        if reuse:  # resize or resume: same decision and prices, only the size changes (no new LLM call)
            decision = reuse
        else:
            spot = provider().technicals(ticker)["spot"]
            decision = policy.decide({
                "attempt": attempt, "ticker": ticker, "spot": spot, "dossier": d, "market": {**corr, "realized_vol": vol},
                "fund": {"nav": snap.nav, "cash": snap.settled_cash, "holdings": holdings, "mandate": mandate} if snap else {"note": "no fund set yet", "min_buy_conviction": mandate.get("min_buy_conviction")},
                "question_allowed": state.research_rounds < MAX_RESEARCH_ROUNDS,
            })
        floor = mandate.get("min_buy_conviction", 0.0)
        decision, floored = apply_buy_floor(decision, d.conviction_score, floor)
        action = decision["action"]
        if floored:
            ev.text = f"→ wanted BUY, but conviction {d.conviction_score:.1f} is below the {floor:g} buy floor → HOLD"
        elif action == "NEED_MORE_RESEARCH" and state.research_rounds >= MAX_RESEARCH_ROUNDS:
            ev.text = f"→ wanted more research, but the {MAX_RESEARCH_ROUNDS}-round cap is reached → HOLD"
            decision, action = {"action": "HOLD", "rationale": "Still uncertain after the extra research round."}, "HOLD"
        elif action == "NEED_MORE_RESEARCH":
            ev.text = f"→ ask Research: {decision['question']}"
        elif action == "HOLD":
            ev.text = "→ HOLD"
        else:
            ev.text = f"→ {action} {ticker} | conviction {d.conviction_score:.1f} | limit ${decision['limit_price']:.2f} | stop ${decision['stop_loss_price']:.2f}"

    if action == "NEED_MORE_RESEARCH":
        question = decision["question"]
        record = record_handoff(
            run_id=run, seq=seq, agent_id=AGENT, status="COMPLETED", started_at=started, consumed=consumed, **_llm_fields(policy),
            handoff=HandoffSummary(signal="NEEDS MORE RESEARCH", opinion=clip(f"Research should answer: {question}", 240), why_rationale=f"Conviction {d.conviction_score:.1f} is high, but the dossier does not yet cover this question, which affects sizing confidence."),
            plain=explain.pm_question(ticker, question),
        )
        return {**base, "pm_route": "research", "pm_question": question, "handoff_log": [record]}

    if action == "HOLD":
        return {**base, **_finish(state, seq, started, consumed, _hold(ticker, decision.get("rationale", "")), "hold", llm=_llm_fields(policy))}

    cap = None
    if feedback and snap:
        cap, why_not = _revision_cap(feedback, snap, mandate, ticker, vol, corr)
        if cap <= 0:  # no size clears the failed rules: stop instead of re-submitting the same trade
            intent = _hold(ticker, why_not)
            return {**base, **_finish(state, seq, started, consumed, intent, "hold", llm=_llm_fields(policy))}
    sized = registry.use(
        run, AGENT, "size_position",
        conviction=d.conviction_score, realized_vol=vol, max_corr=corr["max_corr"], nav=snap.nav if snap else None,
        limit_price=decision["limit_price"], mandate=mandate, cap_pct=cap,
    ).data
    if sized["weight_pct"] == 0 or (snap and sized["shares"] == 0):
        intent = _hold(ticker, "Position size rounds to zero within the mandate.")
        return {**base, **_finish(state, seq, started, consumed, intent, "hold")}
    if feedback and state.intent and sized["shares"] >= state.intent.shares:  # a "resize" that doesn't shrink is not a resize
        intent = _hold(ticker, "Resizing could not make the trade small enough to clear the failed safety rules.")
        return {**base, **_finish(state, seq, started, consumed, intent, "hold", llm=_llm_fields(policy))}

    rationale = f"Conviction {d.conviction_score:.1f}; " + (f"{corr['max_corr_holding']} correlation {corr['max_corr']:.2f}; " if corr["max_corr_holding"] else "no overlap with holdings; ") + f"vol {vol:.0%}."
    if snap is None:
        rec = Recommendation(
            action=action, ticker=ticker, target_weight_pct=sized["weight_pct"], limit_price=decision["limit_price"],
            stop_loss_price=decision["stop_loss_price"], stop_loss_pct=round((decision["limit_price"] - decision["stop_loss_price"]) / decision["limit_price"] * 100, 1),
            rationale=rationale,
        )
        record = record_handoff(
            run_id=run, seq=seq, agent_id=AGENT, status="COMPLETED", started_at=started, consumed=consumed, output=rec, **_llm_fields(policy),
            handoff=HandoffSummary(
                signal=f"{action} ADVICE: {rec.target_weight_pct:.1f}% of fund",
                opinion=f"The Vault needs the user's fund to size and check a limit {action.lower()} at ${rec.limit_price:,.2f}.",
                why_rationale=f"Conviction {d.conviction_score:.1f} sized by formula at {rec.target_weight_pct:.1f}% of the fund; no holdings to overlap with.",
            ),
            plain=explain.pm_recommendation(rec),
        )
        return {**base, "recommendation": rec, "pm_route": "risk", "pm_question": None, "handoff_log": [record]}

    intent = TradeIntent(
        action=action, ticker=ticker, target_weight_pct=sized["weight_pct"], dollar_amount=sized["dollar_amount"],
        shares=sized["shares"], limit_price=decision["limit_price"], stop_loss_price=decision["stop_loss_price"], rationale=rationale,
    )
    return {**base, **_finish(state, seq, started, consumed, intent, "risk", resized=bool(feedback), corr=corr, llm=_llm_fields(policy))}


def _finish(state: FundGraphState, seq: int, started: str, consumed: list, intent: TradeIntent, route: str, resized: bool = False, corr: dict | None = None, llm: dict | None = None) -> dict[str, Any]:
    nav = state.portfolio.nav if state.portfolio else 0.0
    if intent.action == "HOLD":
        handoff = HandoffSummary(signal="HOLD", opinion="No trade; the run ends here.", why_rationale=clip(intent.rationale or "The case does not justify risking capital.", 400))
    else:
        why = f"Conviction {state.dossier.conviction_score:.1f} sized by formula at {intent.target_weight_pct:.1f}% NAV"
        if corr and corr["max_corr"] > 0.6:
            why += f", trimmed for {corr['max_corr']:.2f} correlation with {corr['max_corr_holding']}"
        if resized:
            why += ", resized to clear the Risk Gate"
        handoff = HandoffSummary(
            signal=f"{intent.action} INTENT: {intent.target_weight_pct:.1f}% NAV (${intent.dollar_amount / 1000:,.0f}k)",
            opinion=f"Risk Gate should verify a {intent.shares}-share limit {intent.action.lower()} at ${intent.limit_price:,.2f}.",
            why_rationale=why + ".",
        )
    record = record_handoff(
        run_id=state.run_id, seq=seq, agent_id=AGENT, status="COMPLETED", started_at=started, consumed=consumed, **(llm or {}),
        output=intent, handoff=handoff, plain=explain.pm(intent, nav, resized),
    )
    return {"intent": intent, "pm_route": route, "pm_question": None, "handoff_log": [record]}
