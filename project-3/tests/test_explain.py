from nexus import explain
from tests.conftest import run_pipeline


def test_every_completed_role_has_plain_english():
    run = run_pipeline("NVDA")
    for r in run.records:
        assert r.plain and r.plain.headline and r.plain.what_it_means and r.plain.so_what


def test_plain_english_uses_the_artifact_numbers():
    f = run_pipeline("NVDA").final
    plain = {r.agent_id: r.plain for r in f["handoff_log"]}
    assert "8.6" in plain["research_analyst"].headline
    assert "689 shares" in plain["portfolio_manager"].what_it_means
    assert "$51,450" in plain["risk_gate"].what_it_means  # 2.10% VaR × $2.45M NAV, in dollars
    assert "$2,450,073.03" in plain["portfolio_ledger"].what_it_means


def test_rejection_explains_the_rule_in_plain_words():
    run = run_pipeline("AAPL")
    assert "wash-sale" in run.by_agent("risk_gate")[0].plain.what_it_means


def test_glossary_covers_handoff_jargon():
    for term in ("NAV", "bps", "RSI", "VaR", "wash sale", "VWAP", "slippage"):
        assert term in explain.GLOSSARY
