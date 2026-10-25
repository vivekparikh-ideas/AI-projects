"""End-to-end runs of the four M1 reference scenarios (REQUIREMENTS §10)."""

import pytest

from nexus import policies
from nexus.schemas import AGENT_ORDER
from nexus.state import MAX_AGENT_TOOL_CALLS
from tests.conftest import run_pipeline


def _assert_handoff_chain_intact(run):
    """Each consumed artifact must be byte-identical to what its producer last emitted."""
    latest = {}
    for r in run.records:
        for c in r.consumed:
            if c.agent_id == "portfolio_ledger" and c.artifact_type == "PortfolioSnapshot":
                continue  # the starting snapshot comes from the ledger store, not a record
            assert latest[(c.agent_id, c.artifact_type)] == c.sha, (r.seq, c)
        if r.produced:
            latest[(r.agent_id, r.produced.artifact_type)] = r.produced.sha


def _assert_every_action_closes(run):
    open_actions = {}
    for e in run.micro_events:
        key = (e["agent_id"], e["action_id"])
        if e["status"] == "IN_PROGRESS":
            assert key not in open_actions, f"nested duplicate {key}"
            open_actions[key] = e
        else:
            assert open_actions.pop(key, None) is not None, f"terminal without start {key}"
    assert not open_actions


def test_nvda_happy_path():
    run = run_pipeline("NVDA")
    f = run.final
    assert [r.agent_id for r in run.records] == list(AGENT_ORDER)
    assert all(r.status == "COMPLETED" for r in run.records)
    assert [r.seq for r in run.records] == [1, 2, 3, 4, 5]
    assert all(r.handoff and r.plain for r in run.records)
    _assert_handoff_chain_intact(run)
    _assert_every_action_closes(run)

    assert [s.tool for s in f["agent_trace"]] == ["sec_get_insider_trades", "get_cap_table", "sec_get_filing_section"]
    assert f["dossier"].conviction_score == 8.6
    assert (f["intent"].shares, f["intent"].dollar_amount, f["intent"].limit_price) == (689, 97906.90, 142.10)
    assert f["risk"].passed_count == 4 and f["risk"].var_after_pct == 2.1
    assert f["receipt"].avg_fill_price == 141.944 and f["receipt"].slippage_bps == -1.1
    assert f["ledger"].nav_after == 2_450_073.03 and f["ledger"].cash_after == 514_200.58
    assert f["ledger"].reconciled and f["ledger"].tax_lot.lot_id == "NVDA-2026-10-21-001"
    assert f["portfolio"].weight_of("NVDA") == pytest.approx(3.99, abs=0.01)


def test_amd_resized_after_concentration_fail():
    run = run_pipeline("AMD")
    risk = run.by_agent("risk_gate")
    assert [r.status for r in risk] == ["REJECTED", "COMPLETED"]
    first = risk[0].output["rules"][0]
    assert first["name"] == "concentration" and not first["passed"] and first["observed"] == 5.9
    assert risk[1].output["rules"][0]["observed"] == 4.49
    assert len(run.by_agent("portfolio_manager")) == 2
    assert run.final["intent"].shares == 200
    assert run.final["risk_revisions"] == 1
    assert run.final["ledger"].reconciled
    _assert_handoff_chain_intact(run)
    _assert_every_action_closes(run)


def test_aapl_wash_sale_hard_reject():
    run = run_pipeline("AAPL")
    risk = run.by_agent("risk_gate")
    assert len(risk) == 1 and risk[0].status == "REJECTED"
    failed = [r["name"] for r in risk[0].output["rules"] if not r["passed"]]
    assert failed == ["wash_sale"]
    assert risk[0].handoff.signal == "REJECTED (3/4 Rules Passed)"
    assert [r.status for r in run.by_agent("execution_trader") + run.by_agent("portfolio_ledger")] == ["SKIPPED", "SKIPPED"]
    assert run.final.get("receipt") is None and run.final.get("ledger") is None


def test_pm_asks_research_once_then_trades():
    run = run_pipeline("NVDA", "needs_more")
    assert run.final["research_rounds"] == 2
    assert [r.agent_id for r in run.records][:4] == ["research_analyst", "portfolio_manager", "research_analyst", "portfolio_manager"]
    assert run.by_agent("portfolio_manager")[0].handoff.signal == "NEEDS MORE RESEARCH"
    assert "78.4%" in run.final["dossier"].notes[0]
    assert run.final["ledger"].nav_after == 2_450_073.03
    _assert_handoff_chain_intact(run)


def test_research_loop_cap_forces_hold():
    run = run_pipeline("NVDA", "loop_forever")
    assert run.final["research_rounds"] == 2
    assert run.final["intent"].action == "HOLD"
    assert [r.status for r in run.records[-3:]] == ["SKIPPED", "SKIPPED", "SKIPPED"]


def test_react_tool_cap(monkeypatch):
    """An agent that never stops calling tools is cut off at the cap, told to submit, and fails to HOLD."""

    def greedy(self):
        return policies.Action(kind="tool", tool="get_institutional_holders", reason="one more look")

    monkeypatch.setattr(policies.ScriptedResearchPolicy, "next_action", greedy)
    run = run_pipeline("NVDA")
    assert len(run.final["agent_trace"]) == MAX_AGENT_TOOL_CALLS
    think = [e for e in run.micro_events if e["action_id"] == "agent_think" and e["status"] == "COMPLETED"]
    assert any("cap reached" in e["evidence_snippet"] for e in think)
    assert run.by_agent("research_analyst")[0].status == "FAILED"
    assert run.final["intent"].action == "HOLD"


def test_ungrounded_dossier_fails_then_holds(monkeypatch):
    original = policies.ScriptedResearchPolicy.synthesize

    def invent(self):
        out = original(self)
        out["bull_case"] = "Revenue will grow 400% next year."
        return out

    monkeypatch.setattr(policies.ScriptedResearchPolicy, "synthesize", invent)
    run = run_pipeline("NVDA")
    research = run.by_agent("research_analyst")[0]
    assert research.status == "FAILED" and "400" in research.handoff.why_rationale
    submits = [e for e in run.micro_events if e["action_id"] == "submit_dossier" and e["status"] == "FAILED"]
    assert len(submits) == 2  # original attempt + one repair
    assert run.final["intent"].action == "HOLD"
    assert run.by_agent("execution_trader")[0].status == "SKIPPED"
