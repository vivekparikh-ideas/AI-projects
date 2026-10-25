"""Deterministic math that M1 already does for real: scorecard, sizing, risk rules, slicing, books."""

import pytest

from nexus.mock_data import MANDATE
from nexus.schemas import RealizedLoss
from nexus.tools import execution, pm, research, risk
from nexus.tools.research import GroundingError, check_grounding


def _score(ticker):
    f, v, t = (research.sec_get_financials(ticker).data, research.get_valuation(ticker).data, research.compute_technicals(ticker).data)
    return research.compute_scorecard(f, v, t).data["base_score"]


@pytest.mark.parametrize("ticker,expected", [("NVDA", 8.1), ("AMD", 6.0), ("AAPL", 5.4)])
def test_scorecard(ticker, expected):
    assert _score(ticker) == expected


def test_size_position_nvda():
    d = pm.size_position(conviction=8.6, realized_vol=0.48, max_corr=0.71, nav=2_450_000, limit_price=142.10, mandate=MANDATE).data
    assert d == {"weight_pct": 4.0, "shares": 689, "dollar_amount": 97906.90}


def test_size_position_respects_cap():
    d = pm.size_position(conviction=7.4, realized_vol=0.50, max_corr=0.52, nav=2_450_000, limit_price=158.55, mandate=MANDATE, cap_pct=1.3).data
    assert d["weight_pct"] == 1.3 and d["shares"] == 200


def test_size_position_zero_below_min_conviction():
    d = pm.size_position(conviction=4.9, realized_vol=0.3, max_corr=0.1, nav=2_450_000, limit_price=100, mandate=MANDATE).data
    assert d["shares"] == 0


def test_concentration_counts_existing_holding():
    r = risk.check_concentration("AMD", existing_pct=3.2, add_pct=2.7, limit_pct=5.0)
    assert not r.passed and r.observed == 5.9 and r.resizable


def test_wash_sale_window():
    losses = [RealizedLoss(ticker="AAPL", date="2026-10-09", amount_usd=-4210)]
    assert not risk.check_wash_sale("AAPL", losses, "2026-10-21", 30).passed
    assert risk.check_wash_sale("AAPL", losses, "2026-11-20", 30).passed
    assert risk.check_wash_sale("MSFT", losses, "2026-10-21", 30).passed
    assert not risk.check_wash_sale("AAPL", losses, "2026-10-21", 30).resizable


def test_marginal_var_nvda():
    r = risk.compute_marginal_var("NVDA", add_pct=97906.90 / 2_450_000 * 100, var_before_pct=1.9, limit_pct=2.5, realized_vol=0.48, corr_to_portfolio=0.67)
    assert r.observed == 2.1 and r.passed


def test_twap_slices():
    assert execution.plan_twap_slices(689).data["slices"] == [138, 138, 138, 138, 137]
    assert sum(execution.plan_twap_slices(1003, 7).data["slices"]) == 1003


def test_fill_never_above_limit():
    order = execution.submit_limit_order("cid", "NVDA", "BUY", 10, limit_price=141.94, bid=141.94, seq=1).data
    assert order["price"] <= 141.94


def test_grounding_catches_invented_numbers():
    src = [research.get_valuation("NVDA")]
    check_grounding(["Trades at 32.4x forward earnings."], src)
    with pytest.raises(GroundingError, match="99"):
        check_grounding(["Trades at 99x forward earnings."], src)
