"""Optional fund (D-021): runs without a fund give advice; entering cash resumes without re-research."""

from typing import Any

from nexus.fund import FundConfig, Holding, load_fund, mandate_for, save_fund
from nexus.graph import build_graph, resume_with_fund
from tests.conftest import run_pipeline


def _resume(final: dict[str, Any], fund: FundConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mode, chunk in build_graph(entry="portfolio_manager").stream(resume_with_fund(final, fund), config={"configurable": {"speed": 0, "approval": "auto"}}, stream_mode=["values"]):
        out = chunk
    return out


def test_presets_set_the_limits():
    assert mandate_for("careful")["max_single_name_pct"] == 3.0
    assert mandate_for("balanced")["max_var_pct"] == 2.5
    assert mandate_for("bold")["max_single_name_pct"] == 8.0


def test_fund_snapshot_values_holdings_and_cash():
    fund = FundConfig(cash=50_000, holdings=[Holding(ticker="AMD", shares=100, cost_basis=120.0)])
    snap = fund.snapshot()
    assert snap.nav == 50_000 + 100 * 158.70  # marked at the fixture close
    assert snap.weight_of("AMD") == round(15_870 / 65_870 * 100, 2)
    assert snap.current_var_pct > 0 and snap.tax_lots[0].cost_basis == 120.0


def test_fund_round_trips_through_yaml(tmp_path):
    fund = FundConfig(cash=25_000, preset="careful", holdings=[Holding(ticker="MSFT", shares=10, cost_basis=400)])
    save_fund(fund, tmp_path / "fund.yaml")
    assert load_fund(tmp_path / "fund.yaml") == fund


def test_no_fund_run_ends_with_advice_and_awaits_fund():
    run = run_pipeline("NVDA", fund=None)
    rec = run.final["recommendation"]
    assert rec.action == "BUY" and rec.target_weight_pct == 4.2  # no holdings → no correlation trim
    assert rec.stop_loss_pct == 9.9
    assert run.final.get("intent") is None
    assert run.by_agent("portfolio_manager")[0].handoff.signal == "BUY ADVICE: 4.2% of fund"
    assert [r.status for r in run.records[-3:]] == ["AWAITING_FUND"] * 3
    fund_events = [e for e in run.micro_events if e["action_id"] == "fund_check" and e["status"] == "COMPLETED"]
    assert "No fund set" in fund_events[0]["evidence_snippet"]


def test_entering_cash_resumes_at_the_pm_without_re_research():
    first = run_pipeline("NVDA", fund=None).final
    final = _resume(first, FundConfig(cash=100_000))
    agents = [r.agent_id for r in final["handoff_log"]]
    assert agents.count("research_analyst") == 1  # research was not repeated
    assert final["intent"].shares == 29 and final["intent"].target_weight_pct == 4.2
    assert final["risk"].approved
    assert final["ledger"].reconciled and final["ledger"].cash_before == 100_000


def test_careful_preset_sizes_smaller():
    run = run_pipeline("NVDA", fund=FundConfig(cash=100_000, preset="careful"))
    assert run.final["intent"].target_weight_pct == 2.5  # 3% max × 0.9 ramp × 0.94 vol


def test_buy_floor_turns_low_conviction_buys_into_hold():
    """D-034: AAPL scores 6.4; with the floor raised to 7.0 Marcus's BUY becomes HOLD in code."""
    run = run_pipeline("AAPL", fund=FundConfig(cash=100_000, mandate_overrides={"min_buy_conviction": 7.0}))
    assert run.final["intent"].action == "HOLD"
    assert "buy floor" in run.final["intent"].rationale
    assert run_pipeline("AAPL", fund=FundConfig(cash=100_000)).final["intent"].action == "BUY"  # default 6.0 floor
