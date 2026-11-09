"""The eval harness, offline (D-045): snapshots recorded from fixture data, scripted policies, no network."""

from __future__ import annotations

import copy
import csv
from pathlib import Path

import pytest

from evals import cases as C
from evals import report
from evals import run_evals as R
from nexus import data
from nexus.data import snapshot
from nexus.data.fixture import FixtureProvider
from nexus.nodes.portfolio_manager import apply_buy_floor
from nexus.tools import research as tools


@pytest.fixture()
def snap_dir(tmp_path: Path) -> Path:
    snapshot.save(snapshot.record(FixtureProvider(), "NVDA"), tmp_path)
    yield tmp_path
    data.use("fixture")


def _base_score(calls: dict) -> float:
    data.set_provider(snapshot.SnapshotProvider({"ticker": "NVDA", "as_of": "2026-10-21", "calls": calls}))
    fin, val, tech = tools.sec_get_financials("NVDA"), tools.get_valuation("NVDA"), tools.compute_technicals("NVDA")
    return tools.compute_scorecard(fin.data, val.data, tech.data).data["base_score"]


def test_replay_matches_the_recorded_provider(snap_dir):
    fx = FixtureProvider()
    p = R.load_snapshot("NVDA", snap_dir)
    assert p.as_of() == fx.as_of()
    assert p.financials("NVDA", 4) == fx.financials("NVDA", 4)
    assert p.insider("NVDA", 90) == fx.insider("NVDA", 90)
    assert p.section("NVDA", "10-K", "risk_factors") == fx.section("NVDA", "10-K", "risk_factors")
    with pytest.raises(RuntimeError, match="KeyError"):  # the fixture has no MD&A: the error was recorded and replays
        p.section("NVDA", "10-K", "mda")
    assert p.market("NVDA", {}) == fx.market("NVDA", {})
    assert p.source("section", "NVDA", "10-Q") == fx.source("section", "NVDA", "10-Q")
    assert p.misses == []


def test_a_missing_key_is_loud_and_logged(snap_dir):
    p = R.load_snapshot("NVDA", snap_dir)
    with pytest.raises(snapshot.SnapshotMiss):
        p.market("NVDA", {"AMD": 3.2})
    with pytest.raises(snapshot.SnapshotMiss):
        p.close("AAPL")
    assert len(p.misses) == 2


def test_recorded_errors_replay_as_errors(snap_dir):
    p = R.load_snapshot("NVDA", snap_dir, C.p_insider_error)
    with pytest.raises(RuntimeError, match="simulated outage"):
        p.insider("NVDA", 90)
    assert p.misses == []


@pytest.mark.parametrize("change", C.CHANGES, ids=lambda ch: ch.title)
def test_planted_changes_never_move_the_base_score(snap_dir, change):
    original = snapshot.load(snap_dir / "NVDA.json")["calls"]
    patched = copy.deepcopy(original)
    change.patch(patched)
    assert patched != original, "the patch changed nothing"
    assert _base_score(patched) == _base_score(original)


def test_insider_patch_keeps_summary_and_numbers_consistent(snap_dir):
    calls = snapshot.load(snap_dir / "NVDA.json")["calls"]
    C.p_insider_selling(calls)
    v = calls[snapshot.key("insider", 90)]
    assert (v["sales"], v["planned_sales"], v["open_market_buys"]) == (40, 0, 0)
    assert v["summary"].startswith("40 Form 4 filings with sales (0 under 10b5-1 plans)")
    assert calls[snapshot.key("insider", 30)]["sales"] <= v["sales"] <= calls[snapshot.key("insider", 180)]["sales"]


def test_buy_floor_is_one_function():
    held, floored = apply_buy_floor({"action": "BUY", "limit_price": 100}, 5.9, 6.0)
    assert floored and held["action"] == "HOLD"
    kept, floored = apply_buy_floor({"action": "BUY", "limit_price": 100}, 6.0, 6.0)
    assert not floored and kept["action"] == "BUY"


def test_selection_adds_the_controls_a_case_needs():
    ids = [c.case_id for c in R.select(1, None, ["SIG-KO-1", "ROB-03"], False)]
    assert "SIG-KO-C" in ids and "SIG-KO-1" in ids and "ROB-03" in ids
    phase1 = R.select(1, None, None, False)
    assert len(phase1) == 58 and all(c.phase == 1 for c in phase1)


def test_csv_export_lists_every_case(tmp_path):
    out = tmp_path / "cases.csv"
    n = R.export_csv(out)
    rows = list(csv.DictReader(out.open()))
    assert n == len(rows) == len(C.ALL) == 78
    assert not any(r["case_id"] in ("SIG-JPM-4", "PM-14") for r in rows)
    assert rows[0].keys() == set(C.CSV_COLUMNS)
    one = tmp_path / "phase1.csv"
    assert R.export_csv(one, phase=1) == 58
    assert {r["ticker"].split()[0] for r in csv.DictReader(one.open())} == set(C.PHASE1_TICKERS)


class StubPM:
    """Stands in for Claude: always BUY at a valid price, so floor cases fail on the raw answer."""

    usage = None

    def __init__(self) -> None:
        self.last_raw = None

    def decide(self, ctx):
        spot = ctx["spot"]
        self.last_raw = {"action": "BUY", "question": "", "limit_price": round(spot * 1.005, 2), "stop_loss_price": round(spot * 0.9, 2), "rationale": "Stub."}
        return dict(self.last_raw)


def test_harness_end_to_end_offline(snap_dir, tmp_path):
    selected = C.planted("NVDA") + [C.regression("NVDA", 1)] + [c for c in C.robustness() if c.case_id in ("ROB-02", "ROB-07")]
    selected += [c for c in C.pm_cases(base="NVDA") if c.case_id in ("PM-01", "PM-03", "PM-05")]
    by_case = R.run_cases(selected, reruns=2, snapshot_dir=snap_dir, workers=0, budget=None, mode="scripted", pm_policy_factory=StubPM)
    results = {c["case_id"]: c for c in R.grade_all(selected, by_case)}

    assert not [cid for cid, c in results.items() if c["status"] == "INVALID"], "a case read data the snapshot lacks"
    assert results["SIG-NVDA-C"]["status"] == "PASS"            # scripted Ava is perfectly stable
    assert results["SIG-NVDA-1"]["metrics"]["delta"] == 0.0     # ...and never reacts, which the grader catches
    assert results["SIG-NVDA-1"]["status"] == "FAIL"
    assert results["REG-NVDA"]["status"] == "PASS"
    assert all(r["round2_ok"] for r in results["ROB-07"]["runs"])
    assert results["PM-01"]["status"] == "PASS"
    assert results["PM-03"]["status"] == "FAIL"                 # raw BUY below the floor...
    assert results["PM-03"]["metrics"]["final_actions"] == ["HOLD", "HOLD"]  # ...that code turned into HOLD
    assert results["PM-05"]["status"] == "FAIL"                 # a stub that never sells

    prov = R.provenance(selected, snap_dir, 2, "pytest", "scripted")
    result = {"run_id": "test-run", "started": "2026-11-05T10:00:00", "finished": "2026-11-05T10:01:00", "duration_s": 60,
              "provenance": prov, "summary": R.summarize(list(results.values())), "cases": list(results.values()), "budget_usd": 1, "estimate_usd": 0}
    html = report.render(result)
    assert html.startswith("<!DOCTYPE html>") and "SIG-NVDA-1" in html and "PM-03" in html and "SCRIPTED" in html

    before = copy.deepcopy(result)
    before["run_id"] = "baseline-run"
    for c in before["cases"]:
        if c["case_id"] == "PM-03":
            c["status"] = "PASS"
    assert report.compare(result, before)["PM-03"] == "new"
    assert "NEW FAIL" in report.render(result, before, history=[])


def test_offline_checks_on_a_recorded_snapshot(snap_dir):
    from evals import offline

    pm = [c for c in C.pm_cases(base="NVDA") if c.case_id in ("PM-01", "PM-13", "PM-16")]
    rob = [c for c in C.robustness() if c.case_id in ("ROB-02", "ROB-04")]
    for c in rob:
        c.ticker = "NVDA"
    items = {it["id"]: it for it in offline.run(["NVDA", "ZZZZ"], snap_dir, pm_cases=pm, rob_cases=rob)}
    assert items["COV-ZZZZ"]["status"] == "FAIL" and offline.blocking(list(items.values())) == ["COV-ZZZZ"]
    assert items["COV-NVDA"]["status"] == "REVIEW"  # the fixture has no MD&A: a recorded failure, flagged once
    assert all(items[f"PLANT-NVDA-{ch.code}"]["status"] == "PASS" for ch in C.CHANGES)
    assert items["GUARD-prices"]["status"] == items["GUARD-floor"]["status"] == "PASS"
    assert items["GROUND-NVDA"]["status"] == "PASS"
    assert all(items[f"DOSSIER-{c.case_id}"]["status"] == "PASS" for c in pm)
    assert data.provider().name == "fixture"  # the checks restore the test provider


def test_conviction_range_stops_at_zero_for_a_low_base_score(snap_dir):
    from evals import offline

    calls = snapshot.load(snap_dir / "NVDA.json")
    calls["calls"][snapshot.key("valuation")]["fwd_pe"] = 60.0          # value score 0
    calls["calls"][snapshot.key("financials", 1)]["revenue_growth_pct"] = -20.0  # growth score 0
    calls["calls"][snapshot.key("financials", 1)]["net_share_change_pct"] = 3.0  # dilution score 0
    calls["calls"][snapshot.key("technicals")].update(spot=100.0, dma50=120.0, dma200=130.0, rsi14=20.0)  # trend 0
    snapshot.save(calls, snap_dir)
    check = offline.conviction_range("NVDA", snap_dir)[0]
    assert check.passed is True and "0.0…1.5 (stops at 0)" in check.observed  # D-046: conviction stops at 0


def test_offline_report_is_its_own_kind(snap_dir):
    from evals import offline

    items = offline.run(["NVDA"], snap_dir, pm_cases=[], rob_cases=[])
    result = {"run_id": "t-offline", "kind": "offline", "started": "2026-11-05T10:00:00", "duration_s": 0, "offline": {"summary": offline.summarize(items), "items": items},
              "provenance": R.offline_provenance(["NVDA"], snap_dir, "pytest")}
    html = report.render(result, history=[])
    assert "offline checks" in html and "Part 2 · Online evals" in html and "Not run" in html


def test_conviction_stops_at_0_and_10():
    assert tools.conviction_from(1.0, -1.5) == 0.0
    assert tools.conviction_from(9.2, 1.5) == 10.0
    assert tools.conviction_from(5.2, -0.4) == 4.8


def test_planted_grader_asks_only_for_the_room_left():
    assert C.room_bounds(None, -0.3, 0.0) == (None, -0.3, "")              # plenty of room: the normal bar
    lo, hi, note = C.room_bounds(None, -0.5, -1.2)                          # 0.3 left before −1.5
    assert hi == -0.3 and "0.3 left" in note
    assert C.room_bounds(0.3, None, 1.45)[:2] == (None, None)              # no room: REVIEW
    assert C.room_bounds(-0.1, 0.7, 1.4) == (-0.1, 0.7, "")                # a band is not a "must move" bar


def test_sell_price_band():
    assert C.sell_price_ok({"limit_price": 99.0}, 100.0)
    assert not C.sell_price_ok({"limit_price": 95.0}, 100.0)
    assert not C.sell_price_ok({"limit_price": 101.0}, 100.0)


def test_bank_revenue_tag_is_known():
    from nexus.data.live import REVENUE_TAGS

    assert "RevenuesNetOfInterestExpense" in REVENUE_TAGS


def test_your_verdict_replaces_review_only():
    result = {"cases": [{"case_id": "A", "status": "REVIEW", "suite": "pm_synthetic", "agent": "Marcus", "cost": 0.0, "runs": []},
                        {"case_id": "B", "status": "FAIL", "suite": "pm_synthetic", "agent": "Marcus", "cost": 0.0, "runs": []}],
              "summary": {}}
    assert report.apply_reviews(result, {"A": "PASS"}, "2026-11-06") == ["A"]
    assert result["cases"][0]["status"] == "PASS" and result["cases"][0]["review"]["was"] == "REVIEW"
    assert result["summary"]["total"] == {"PASS": 1, "FAIL": 1}
    report.apply_reviews(result, {"A": "FAIL"}, "2026-11-06")  # a verdict can be changed
    assert result["cases"][0]["status"] == "FAIL"
    with pytest.raises(ValueError, match="only REVIEW"):
        report.apply_reviews(result, {"B": "PASS"}, "2026-11-06")


def test_rescaled_price_keeps_market_cap(snap_dir):
    data.set_provider(R.load_snapshot("NVDA", snap_dir))
    base = R.base_dossier("NVDA")
    pm14 = next(c for c in C.pm_cases(base="NVDA") if c.case_id == "PM-13").pm
    d = R.pm_dossier(base, pm14)
    assert d.technicals.spot * d.dilution.diluted_shares_b == pytest.approx(base.technicals.spot * base.dilution.diluted_shares_b, rel=0.01)


def test_a_dossier_whose_conviction_stops_at_zero_is_valid(snap_dir):
    from nexus.schemas import ResearchDossier

    data.set_provider(R.load_snapshot("NVDA", snap_dir))
    d = R.base_dossier("NVDA")
    card = d.scorecard.model_copy(update={"base_score": 1.0})
    low = d.model_dump() | {"scorecard": card.model_dump(), "llm_adjustment": -1.2, "conviction_score": tools.conviction_from(1.0, -1.2)}
    assert ResearchDossier.model_validate(low).conviction_score == 0.0  # D-046: the schema accepts what submit_dossier builds


def test_regrade_uses_stored_runs_and_keeps_your_verdicts(snap_dir):
    selected = C.planted("NVDA")[:2]
    by_case = R.run_cases(selected, reruns=2, snapshot_dir=snap_dir, workers=0, budget=None, mode="scripted")
    cases = R.grade_all(selected, by_case)
    result = {"cases": cases, "summary": R.summarize(cases), "provenance": {"cases_sha": "old"}}
    result["cases"][1]["status"] = "PASS"            # pretend an older, looser grader passed it
    changed = R.regrade(result, "2026-11-06")
    assert ("SIG-NVDA-1", "PASS", "FAIL") in changed  # scripted Ava never reacts: today's grader fails it
    assert result["provenance"]["cases_sha"] == R.cases_sha() and result["provenance"]["regraded"] == ["2026-11-06"]


def test_reporting_zero_insider_trades_is_not_an_invented_story():
    assert not C.insider_claims({"bear_case": "Insiders had no sales and no buys in 90 days.", "bull_case": "", "adjustment_reason": "", "notes": []})
    assert not C.insider_claims({"bear_case": "", "bull_case": "", "adjustment_reason": "Insiders made 0 sales and 0 buys in 90 days.", "notes": []})
    assert C.insider_claims({"bear_case": "Insiders sold heavily last quarter.", "bull_case": "", "adjustment_reason": "", "notes": []})
