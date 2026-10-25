"""M2: journey router, research-only and what-if journeys, indicator math, policy guards. No network."""

from typing import Any

import pytest

from nexus.graph import build_graph, initial_state, whatif_state
from nexus.policies import _sanity_check
from nexus.router import Journey, UnknownCommand, parse
from nexus.tools import indicators as ind
from tests.conftest import run_pipeline


@pytest.mark.parametrize("text,expected", [
    ("Evaluate NVDA", Journey("evaluate", "NVDA")),
    ("should I buy amd?", Journey("evaluate", "AMD")),
    ("TSLA", Journey("evaluate", "TSLA")),
    ("Research TSLA", Journey("research", "TSLA")),
    ("Can I add $50k of AMD?", Journey("whatif", "AMD", 50_000)),
    ("what if I buy 12,500 of aapl", Journey("whatif", "AAPL", 12_500)),
    ("Check my stocks", Journey("monitor")),
    ("scan watchlist", Journey("scan")),
])
def test_router(text, expected):
    assert parse(text) == expected


def test_router_rejects_noise():
    with pytest.raises(UnknownCommand):
        parse("tell me a joke about bonds")


def _run(state, entry) -> dict[str, Any]:
    final: dict[str, Any] = {}
    for _, chunk in build_graph(entry=entry).stream(state, config={"configurable": {"speed": 0, "approval": "auto"}}, stream_mode=["values"]):
        final = chunk
    return final


def test_research_only_never_reaches_the_pm():
    final = _run(initial_state("NVDA", fund="sample", journey="research"), "research_analyst")
    assert [r.agent_id for r in final["handoff_log"]] == ["research_analyst"]
    assert final["dossier"].conviction_score == 8.6 and final.get("intent") is None


def test_whatif_checks_without_trading():
    final = _run(whatif_state("AMD", 50_000, "sample"), "risk_gate")
    risk = final["risk"]
    assert [r.agent_id for r in final["handoff_log"]] == ["risk_gate"]
    assert not risk.approved and risk.hitl_status == "NOT_REQUIRED"  # 3.20% held + 2.04% added > 5%
    assert final["handoff_log"][0].handoff.signal == "WHAT-IF: FAILS (3/4 Rules)"
    assert final.get("receipt") is None


def test_whatif_needs_at_least_one_share():
    with pytest.raises(ValueError):
        whatif_state("NVDA", 50, "sample")


def test_resume_reuses_advice_prices_without_a_new_decision():
    from nexus.fund import FundConfig
    from nexus.graph import resume_with_fund

    first = run_pipeline("NVDA", fund=None).final
    final = _run(resume_with_fund(first, FundConfig(cash=100_000)), "portfolio_manager")
    pm = [r for r in final["handoff_log"] if r.agent_id == "portfolio_manager"][-1]
    assert pm.output["limit_price"] == first["recommendation"].limit_price
    assert final["intent"].stop_loss_price == 128.00  # 9.9% below $142.10, rounded


def test_indicators():
    closes = [float(x) for x in range(1, 251)]
    assert ind.sma(closes, 50) == pytest.approx(225.5)
    assert ind.rsi_wilder(closes, 14) == 100.0  # only gains
    assert ind.vwap([2, 4], [0, 2], [1, 3], [1, 3], 20) == pytest.approx((1 * 1 + 3 * 3) / 4)
    r = ind.returns([100, 110, 99])
    assert r == pytest.approx([0.10, -0.10])
    assert ind.correlation([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert ind.beta([0.02, -0.02, 0.04], [0.01, -0.01, 0.02]) == pytest.approx(2.0)


def test_pm_price_sanity_check():
    ok = _sanity_check({"action": "BUY", "limit_price": 214.0, "stop_loss_price": 194.5, "rationale": ""}, 213.04)
    assert ok["action"] == "BUY"
    too_high = _sanity_check({"action": "BUY", "limit_price": 230.0, "stop_loss_price": 200.0, "rationale": ""}, 213.04)
    assert too_high["action"] == "HOLD"
    stop_too_tight = _sanity_check({"action": "BUY", "limit_price": 214.0, "stop_loss_price": 212.0, "rationale": ""}, 213.04)
    assert stop_too_tight["action"] == "HOLD"


def test_financials_evidence_tolerates_missing_facts(monkeypatch):
    """Regression (eval, AVGO): a filer without a net-income tag must not crash the evidence line."""
    from nexus.data.fixture import FixtureProvider
    from nexus.tools import research

    base = FixtureProvider().financials("NVDA")
    monkeypatch.setattr(FixtureProvider, "financials", lambda self, t, q=1: {
        **base, "revenue_growth_pct": None, "cash_flow_year": "CY2025", "operating_cash_flow_usd_b": 25.9,
        "net_income_usd_b": None, "receivables_growth_pct": None})
    ev = research.sec_get_financials("NVDA").evidence
    assert "net income n/a" in ev and "n/a% YoY" in ev


def test_live_sources_link_to_the_exact_filing(monkeypatch):
    """D-040: every figure links to where it came from (offline: SEC lookups stubbed)."""
    from nexus.data.live import LiveProvider

    monkeypatch.setenv("NEXUS_SEC_USER_AGENT", "test test@example.com")
    p = LiveProvider()
    monkeypatch.setattr(p, "_cik", lambda t: 1045810)
    monkeypatch.setattr(p, "_submissions", lambda t: [
        {"form": "8-K", "date": "2026-09-03", "accession": "0001045810-26-000080", "doc": "a.htm"},
        {"form": "10-Q", "date": "2026-08-26", "accession": "0001045810-26-000075", "doc": "nvda-20260726.htm"},
        {"form": "10-K", "date": "2026-02-25", "accession": "0001045810-26-000021", "doc": "nvda-20260125.htm"},
    ])
    assert p.source("financials", "NVDA") == ("10-Q filed 2026-08-26", "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/")
    assert p.source("section", "NVDA", "10-K")[1].endswith("/000104581026000021/nvda-20260125.htm")
    assert "type=4" in p.source("insider", "NVDA")[1]
    assert p.source("valuation", "NVDA") == ("Yahoo Finance", "https://finance.yahoo.com/quote/NVDA")


def test_dossier_carries_sources_and_reading_summary():
    d = run_pipeline("NVDA").final["dossier"]
    assert d.sources and d.sources[0].label == "sample data" and d.sources[0].url is None
    assert "3 follow-up checks" in d.reading_summary


def test_var_headroom_inverts_marginal_var():
    from nexus.tools.risk import compute_marginal_var, var_headroom_pct

    h = var_headroom_pct(1.9, 2.5, 0.48, 0.67)
    assert compute_marginal_var("X", h, 1.9, 2.5, 0.48, 0.67).observed == pytest.approx(2.5, abs=0.01)
    assert var_headroom_pct(2.6, 2.5, 0.48, 0.67) == 0.0  # already over the limit: no room


def _run_with_mandate(ticker, **overrides):
    state = initial_state(ticker, fund="sample")
    state = state.model_copy(update={"mandate": {**state.mandate, **overrides}})
    return _run(state, "research_analyst")


def test_var_failure_really_shrinks_the_trade():
    """Bug (promo session): a VaR fail re-submitted the same size. Now the revision fits the VaR headroom."""
    final = _run_with_mandate("NVDA", max_var_pct=2.0)  # 689 sh would take VaR 1.90% → 2.10%
    risk = [r for r in final["handoff_log"] if r.agent_id == "risk_gate"]
    assert [r.status for r in risk] == ["REJECTED", "COMPLETED"]
    assert final["intent"].shares < 689 and final["risk"].var_after_pct <= 2.0


def test_no_var_headroom_holds_without_resubmitting():
    final = _run_with_mandate("NVDA", max_var_pct=1.8)  # portfolio already at 1.90%
    assert final["intent"].action == "HOLD" and "worst-day loss is already 1.90%" in final["intent"].rationale
    assert len([r for r in final["handoff_log"] if r.agent_id == "risk_gate"]) == 1  # no pointless second check
