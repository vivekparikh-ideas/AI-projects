import pytest
from pydantic import ValidationError

from nexus.schemas import HandoffSummary, MicroActionEvent, Scorecard, TradeIntent
from nexus.tools.research import submit_dossier

EVENT = dict(run_id="r", agent_id="risk_gate", action_id="x", action_label="X", status="COMPLETED", timestamp="t")


def test_micro_action_accepts_valid_event():
    assert MicroActionEvent(**EVENT).status == "COMPLETED"


@pytest.mark.parametrize("field,value", [("agent_id", "compliance_bot"), ("status", "DONE")])
def test_micro_action_rejects_unknown_literals(field, value):
    with pytest.raises(ValidationError):
        MicroActionEvent(**{**EVENT, field: value})


def test_contracts_forbid_extra_fields():
    with pytest.raises(ValidationError):
        HandoffSummary(signal="s", opinion="o", why_rationale="w", mood="great")


def _intent(**kw):
    base = dict(action="BUY", ticker="NVDA", target_weight_pct=4.0, dollar_amount=97906.90, shares=689, limit_price=142.10, stop_loss_price=128.00)
    return TradeIntent(**{**base, **kw})


def test_trade_intent_valid():
    assert _intent().shares == 689


def test_trade_intent_dollars_must_match_shares_times_limit():
    with pytest.raises(ValidationError, match="shares × limit_price"):
        _intent(dollar_amount=100_000)


def test_buy_stop_must_be_below_limit():
    with pytest.raises(ValidationError, match="stop_loss_price"):
        _intent(stop_loss_price=150.0)


def test_hold_must_be_empty():
    with pytest.raises(ValidationError, match="HOLD"):
        _intent(action="HOLD")


def test_conviction_must_equal_base_plus_adjustment():
    from nexus.tools import research

    results = {name: getattr(research, name)("NVDA") for name in ("sec_get_financials", "get_valuation", "compute_technicals")}
    results["compute_scorecard"] = research.compute_scorecard(results["sec_get_financials"].data, results["get_valuation"].data, results["compute_technicals"].data)
    synthesis = dict(bull_case="Revenue +94% YoY.", bear_case="32.4x forward earnings.", llm_adjustment=0.5, adjustment_reason="Insider sales are planned.")
    d = submit_dossier("NVDA", results, synthesis, [])
    assert d.conviction_score == 8.6
    with pytest.raises(ValidationError, match="conviction_score"):
        d.model_validate({**d.model_dump(), "conviction_score": 9.9})


def test_llm_adjustment_is_bounded():
    from nexus.schemas import ResearchDossier

    assert ResearchDossier.model_fields["llm_adjustment"].metadata  # ge/le constraints present
    with pytest.raises(ValidationError):
        Scorecard(growth=1, trend=1, valuation=1, dilution=1)  # base_score required
