"""Eval harness for Ava and Marcus on frozen snapshots (D-012, D-045).

Inputs are replayed from evals/snapshots/ (record them first with evals/record.py), so runs differ only
by the model and the prompts. Cases live in evals/cases.py. Model calls cost money; data costs nothing.

    python evals/run_evals.py --dry-run                     # list the cases and the cost estimate
    python evals/run_evals.py --quick --yes                 # P1 cases, 1 rerun each (iterating on a prompt)
    python evals/run_evals.py --yes                         # Phase 1, 3 reruns (before accepting a change)
    python evals/run_evals.py --suite pm_synthetic --yes    # one suite
    python evals/run_evals.py --cases SIG-KO-1,PM-03 --yes  # chosen cases (their controls are added)
    python evals/run_evals.py --csv                         # export the cases to evals/golden_cases.csv
    python evals/report.py --accept evals/results/<run>.json  # make a run the baseline new runs compare with

Each run writes evals/results/<YYYY-MM-DD-HHMM>.json and .html (the report).
Statuses: PASS · FAIL · REVIEW (a person decides) · INVALID (snapshot miss or harness error) · SKIPPED (budget).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import cases as C  # noqa: E402
from nexus import data, llm, policies  # noqa: E402
from nexus.data import snapshot  # noqa: E402

RESULTS_DIR = ROOT / "evals" / "results"
FAILED_SUBMIT = ("submit_dossier", "FAILED")


# ── running one case once ────────────────────────────────────────────────────

def load_snapshot(ticker: str, snapshot_dir: Path, patch: C.Patch | None = None) -> snapshot.SnapshotProvider:
    snap = snapshot.load(snapshot_dir / f"{ticker}.json")
    if patch:
        patch(snap["calls"])
    return snapshot.SnapshotProvider(snap)


def _stream(state: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from nexus.graph import build_graph

    final: dict[str, Any] = {}
    custom: list[dict[str, Any]] = []
    for mode, chunk in build_graph().stream(state, config={"configurable": {"speed": 0, "approval": "auto"}, "recursion_limit": 40},
                                            stream_mode=["custom", "values"]):
        if mode == "values":
            final = chunk
        else:
            custom.append(chunk)
    return final, custom


def _research_fields(final: dict[str, Any], custom: list[dict[str, Any]]) -> dict[str, Any]:
    d = final.get("dossier")
    trace = final.get("agent_trace", [])
    follow_ups = [{"tool": s.tool, "args": dict(s.args)} for s in trace]
    seen = Counter((s["tool"], json.dumps(s["args"], sort_keys=True)) for s in follow_ups)
    records = final.get("handoff_log", [])
    research = [r for r in records if r.agent_id == "research_analyst"]
    failed = sum(1 for c in custom if c.get("type") == "micro_action" and (c["event"]["action_id"], c["event"]["status"]) == FAILED_SUBMIT)
    out = {
        "dossier_ok": d is not None, "follow_ups": follow_ups, "failed_submits": failed,
        "duplicate_calls": sum(v - 1 for v in seen.values()), "max_identical": max(seen.values(), default=0),
        "error_note": research[-1].handoff.why_rationale if research and research[-1].status == "FAILED" and research[-1].handoff else "",
        "cost": round(sum(r.cost_usd or 0 for r in records), 5), "tokens": sum(r.tokens or 0 for r in records),
    }
    if d is not None:
        out.update(base_score=d.scorecard.base_score, llm_adjustment=d.llm_adjustment, conviction=d.conviction_score,
                   bull_case=d.bull_case, bear_case=d.bear_case, adjustment_reason=d.adjustment_reason, notes=list(d.notes))
    return out


def run_ava(case: C.Case, snapshot_dir: Path) -> dict[str, Any]:
    from nexus.graph import initial_state

    prov = data.set_provider(load_snapshot(case.ticker, snapshot_dir, case.patch))
    journey = "evaluate" if case.kind == "regression" else "research"
    run: dict[str, Any] = {}
    try:
        final, custom = _stream(initial_state(case.ticker, fund=None, journey=journey))
        run = _research_fields(final, custom)
        if case.kind == "regression":
            rec, intent = final.get("recommendation"), final.get("intent")
            pick = rec or intent
            run.update(action=pick.action if pick else None, rationale=(intent.rationale if intent else rec.rationale if rec else "") or "",
                       limit_price=pick.limit_price if pick else None, stop_loss_price=pick.stop_loss_price if pick else None)
        if case.kind == "ava_round2" and final.get("dossier") is not None:
            d1 = final["dossier"]
            state2 = initial_state(case.ticker, fund=None, journey="research").model_copy(
                update={"dossier": d1, "research_rounds": 1, "pm_question": case.question})
            final2, custom2 = _stream(state2)
            r2 = _research_fields(final2, custom2)
            d2 = final2.get("dossier")
            new_notes = list(d2.notes[len(d1.notes):]) if d2 is not None else []
            run.update(round2_ok=d2 is not None and final2.get("research_rounds") == 2, round2_follow_ups=r2["follow_ups"],
                       note=new_notes[-1] if new_notes else "", round2_error=r2["error_note"],
                       cost=round(run["cost"] + r2["cost"], 5), tokens=run["tokens"] + r2["tokens"])
    except Exception as exc:  # a crash is a result (FAIL), unless the snapshot was incomplete (INVALID)
        run = {**run, "dossier_ok": run.get("dossier_ok", False), "crash": f"{type(exc).__name__}: {exc}"}
    run["misses"] = list(prov.misses)
    return run


MARKET = {"beta": 0.6, "max_corr_holding": None, "max_corr": 0.0, "corr_to_portfolio": 0.0, "realized_vol": 0.16}


def base_dossier(ticker: str) -> Any:
    """A real dossier built from the snapshot by the research tools, with neutral text and no model call."""
    from nexus.nodes.research_analyst import BASELINE
    from nexus.tools import registry

    agent = "research_analyst"
    results = {name: registry.call(agent, name, ticker=ticker) for name in BASELINE}
    results["compute_scorecard"] = registry.call(agent, "compute_scorecard", financials=results["sec_get_financials"].data,
                                                 valuation=results["get_valuation"].data, technicals=results["compute_technicals"].data)
    for name, kw in (("sec_get_insider_trades", {"days": 90}), ("get_institutional_holders", {}), ("get_cap_table", {})):
        try:
            results[name] = registry.call(agent, name, ticker=ticker, **kw)
        except Exception:
            pass
    synthesis = {"bull_case": C.BULL, "bear_case": C.BEAR, "llm_adjustment": 0.3,
                 "adjustment_reason": "Brand strength and steady cash flows the formula cannot see.", "note": ""}
    return registry.call(agent, "submit_dossier", ticker=ticker, results=results, synthesis=synthesis, trace=[])


def pm_dossier(base: Any, pm: dict[str, Any]) -> Any:
    conv, spot = pm["conviction"], pm["spot"]
    t = base.technicals
    ratio = spot / t.spot if t.spot else 1.0
    tech = t.model_copy(update={"spot": spot, "dma50": round(t.dma50 * ratio, 2), "dma200": round(t.dma200 * ratio, 2), "vwap": round(t.vwap * ratio, 2)})
    # Keep market cap unchanged: a lower price means proportionally more shares, so P/E and FCF yield still fit.
    shares = base.dilution.diluted_shares_b
    dil = base.dilution.model_copy(update={"diluted_shares_b": round(shares / ratio, 2) if shares and ratio else shares})
    card = base.scorecard.model_copy(update={"base_score": round(conv - 0.3, 1)})
    return base.model_copy(update={"conviction_score": conv, "llm_adjustment": 0.3, "scorecard": card, "technicals": tech, "dilution": dil, **pm["edits"]})


def run_pm(case: C.Case, snapshot_dir: Path, policy_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    from nexus.fund import mandate_for
    from nexus.nodes.portfolio_manager import apply_buy_floor

    pm = case.pm
    prov = data.set_provider(load_snapshot(pm["base"], snapshot_dir))
    run: dict[str, Any] = {}
    try:
        dossier = pm_dossier(base_dossier(pm["base"]), pm)
        mandate = {**mandate_for("balanced"), "min_buy_conviction": pm["floor"]}
        if pm["held"] is None:
            fund = {"note": "no fund set yet", "min_buy_conviction": pm["floor"]}
        else:
            holdings = {pm["base"]: pm["held"]} if pm["held"] else {}
            fund = {"nav": 100_000.0, "cash": 100_000.0 * (1 - pm["held"] / 100), "holdings": holdings, "mandate": mandate}
        policy = policy_factory() if policy_factory else policies.make_pm_policy(pm["base"], "default")
        decision = policy.decide({"attempt": 1, "ticker": pm["base"], "spot": pm["spot"], "dossier": dossier, "fund": fund,
                                  "market": MARKET, "question_allowed": pm["question_allowed"]})
        raw = policy.last_raw if hasattr(policy, "last_raw") else dict(decision)
        final, floored = apply_buy_floor(dict(decision), dossier.conviction_score, pm["floor"])
        run = {"raw": raw, "final": final, "floored": floored, "rationale": (raw or {}).get("rationale", ""),
               "cost": round(llm.cost_usd(policy.usage), 5) if getattr(policy, "usage", None) else 0.0,
               "tokens": policy.usage.tokens if getattr(policy, "usage", None) else 0}
    except Exception as exc:
        run = {**run, "crash": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=3)}
    run["misses"] = list(prov.misses)
    return run


def execute(case: C.Case, rerun: int, snapshot_dir: Path, pm_policy_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    run = run_pm(case, snapshot_dir, pm_policy_factory) if case.kind == "pm" else run_ava(case, snapshot_dir)
    run.update(rerun=rerun, seconds=round(time.monotonic() - started, 1))
    return run


def _worker_init(mode: str) -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    policies.set_mode(mode)


def _job(case_id: str, rerun: int, snapshot_dir: str) -> tuple[str, dict[str, Any]]:
    return case_id, execute(C.BY_ID[case_id], rerun, Path(snapshot_dir))


# ── grading ──────────────────────────────────────────────────────────────────

def status_of(case: C.Case, runs: list[dict[str, Any]], checks: list[C.Check]) -> str:
    if not runs or any(r.get("skipped") for r in runs):
        return "SKIPPED"
    if any(r.get("misses") for r in runs):
        return "INVALID"
    if any(c.passed is False for c in checks) or any(r.get("crash") for r in runs):
        return "FAIL"
    return "REVIEW" if any(c.passed is None for c in checks) else "PASS"


def grade_all(selected: list[C.Case], runs_by_case: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for case in selected:
        runs = sorted(runs_by_case.get(case.case_id, []), key=lambda r: r["rerun"])
        live = [r for r in runs if not r.get("skipped")]
        ctx = {"control": [r for r in runs_by_case.get(case.control, []) if not r.get("skipped")]} if case.control else {}
        checks, metrics = case.grade(live, ctx) if live else ([], {})
        crash = next((r["crash"] for r in runs if r.get("crash")), None)
        if crash:
            checks = [*checks, C.Check("No crash", False, crash[:200], "no exception")]
        misses = sorted({m for r in runs for m in r.get("misses", [])})
        if misses:
            checks = [*checks, C.Check("Snapshot complete", False, "missing: " + ", ".join(misses[:5]), "every call recorded")]
        out.append({
            "case_id": case.case_id, "suite": case.suite, "agent": case.agent, "ticker": case.ticker, "title": case.title,
            "priority": case.priority, "phase": case.phase, "setup": case.setup, "field_changed": case.field_changed,
            "planted_value": case.planted_value, "expected": case.expected, "manual_review": case.manual_review,
            "control": case.control, "question": case.question, "pm": dict(case.pm),
            "status": status_of(case, runs, checks), "checks": [c.__dict__ for c in checks], "metrics": metrics, "runs": runs,
            "cost": round(sum(r.get("cost", 0) for r in runs), 4),
        })
    return out


def regrade(result: dict[str, Any], today: str) -> list[tuple[str, str, str]]:
    """Grade the stored runs again with today's graders (no model calls). Your verdicts on REVIEW cases are kept.
    Returns (case id, old status, new status) for every case whose status changed."""
    old = {c["case_id"]: c for c in result["cases"]}
    selected = [C.BY_ID[cid] for cid in old if cid in C.BY_ID]
    fresh = grade_all(selected, {cid: c["runs"] for cid, c in old.items()})
    changed = []
    for c in fresh:
        before = old[c["case_id"]]
        review = before.get("review")
        if review and c["status"] == review["was"]:
            c["review"], c["status"] = review, review["verdict"]
        was = before["status"]
        if c["status"] != was:
            changed.append((c["case_id"], was, c["status"]))
    result["cases"] = fresh
    result["summary"] = summarize(fresh)
    result["provenance"]["cases_sha"] = cases_sha()
    result["provenance"].setdefault("regraded", []).append(today)
    return changed


# ── selection, provenance, main ──────────────────────────────────────────────

def select(phase: int, suites: list[str] | None, ids: list[str] | None, quick: bool) -> list[C.Case]:
    if ids:
        unknown = [i for i in ids if i not in C.BY_ID]
        if unknown:
            raise SystemExit(f"Unknown case ids: {', '.join(unknown)}")
        chosen = [C.BY_ID[i] for i in ids]
    else:
        chosen = [c for c in C.ALL if c.phase <= phase and (not suites or c.suite in suites) and (not quick or c.priority == "P1")]
    ids_set = {c.case_id for c in chosen}
    for c in list(chosen):  # a case compared with a control needs the control in the same run
        if c.control and c.control not in ids_set:
            chosen.append(C.BY_ID[c.control])
            ids_set.add(c.control)
    order = {c.case_id: i for i, c in enumerate(C.ALL)}
    return sorted(chosen, key=lambda c: order.get(c.case_id, 0))


def tickers_needed(selected: list[C.Case]) -> set[str]:
    return {c.pm["base"] if c.kind == "pm" else c.ticker for c in selected}


def cases_sha() -> str:
    return hashlib.sha256((ROOT / "evals" / "cases.py").read_bytes()).hexdigest()[:8]


def provenance(selected: list[C.Case], snapshot_dir: Path, reruns: int, command: str, mode: str) -> dict[str, Any]:
    snaps = {}
    for t in sorted(tickers_needed(selected)):
        s = snapshot.load(snapshot_dir / f"{t}.json")
        snaps[t] = {"as_of": s["as_of"], "sha": snapshot.sha(s), "recorded_at": s.get("recorded_at"), "recorded_from": s.get("recorded_from")}
    return {"model": llm.MODEL if mode == "claude" else "scripted", "effort": llm.EFFORT if mode == "claude" else None, "mode": mode,
            "prompts": {"ava": policies.RESEARCH_PROMPT_VERSION if mode == "claude" else "scripted",
                        "marcus": policies.PM_PROMPT_VERSION if mode == "claude" else "scripted"},
            "cases_file": "evals/cases.py", "cases_sha": cases_sha(), "snapshots": snaps, "reruns": reruns, "command": command}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_suite: dict[str, Counter] = {}
    for r in results:
        by_suite.setdefault(r["suite"], Counter())[r["status"]] += 1
    total = Counter(r["status"] for r in results)
    ava = sum(r["cost"] for r in results if r["agent"] != "Marcus")
    return {"total": dict(total), "cases": len(results), "by_suite": {k: dict(v) for k, v in by_suite.items()},
            "cost": round(ava + sum(r["cost"] for r in results if r["agent"] == "Marcus"), 3), "cost_ava": round(ava, 3),
            "cost_marcus": round(sum(r["cost"] for r in results if r["agent"] == "Marcus"), 3),
            "tokens": sum(run.get("tokens", 0) for r in results for run in r["runs"]),
            "model_runs": sum(1 for r in results for run in r["runs"] if not run.get("skipped"))}


def run_cases(selected: list[C.Case], reruns: int, snapshot_dir: Path, workers: int, budget: float | None,
              on_done: Callable[[str, dict[str, Any], float], None] | None = None, mode: str = "claude",
              pm_policy_factory: Callable[[], Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Controls first, so a budget stop never leaves a planted case without its reference."""
    controls = {c.control for c in selected if c.control}
    ordered = [c for c in selected if c.case_id in controls] + [c for c in selected if c.case_id not in controls]
    jobs = [(c.case_id, i + 1) for c in ordered for i in range(reruns)]
    by_case: dict[str, list[dict[str, Any]]] = {}
    spent = 0.0
    lookup = {c.case_id: c for c in selected}

    def record(cid: str, run: dict[str, Any]) -> None:
        nonlocal spent
        by_case.setdefault(cid, []).append(run)
        spent += run.get("cost", 0) or 0
        if on_done:
            on_done(cid, run, spent)

    if workers <= 0:
        for cid, rerun in jobs:
            if budget is not None and spent >= budget:
                by_case.setdefault(cid, []).append({"rerun": rerun, "skipped": "budget"})
                continue
            record(cid, execute(lookup[cid], rerun, snapshot_dir, pm_policy_factory))
        return by_case

    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=(mode,)) as pool:
        pending: dict[Future, tuple[str, int]] = {}
        queue = list(jobs)
        while queue or pending:
            while queue and len(pending) < workers and (budget is None or spent < budget):
                cid, rerun = queue.pop(0)
                pending[pool.submit(_job, cid, rerun, str(snapshot_dir))] = (cid, rerun)
            if budget is not None and spent >= budget and queue:
                for cid, rerun in queue:
                    by_case.setdefault(cid, []).append({"rerun": rerun, "skipped": "budget"})
                queue.clear()
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                cid, rerun = pending.pop(f)
                try:
                    record(*f.result())
                except Exception as exc:  # the worker itself died
                    record(cid, {"rerun": rerun, "crash": f"worker: {type(exc).__name__}: {exc}", "misses": [], "cost": 0})
    return by_case


def export_csv(path: Path, phase: int | None = None) -> int:
    """All cases, or only one phase's (phase 1 = the 5 tickers that have been run)."""
    chosen = [c for c in C.ALL if phase is None or c.phase == phase]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=C.CSV_COLUMNS)
        w.writeheader()
        for c in chosen:
            w.writerow(C.csv_row(c))
    return len(chosen)


def offline_provenance(tickers: list[str], snapshot_dir: Path, command: str) -> dict[str, Any]:
    snaps = {}
    for t in tickers:
        p = snapshot_dir / f"{t}.json"
        if p.exists():
            s = snapshot.load(p)
            snaps[t] = {"as_of": s["as_of"], "sha": snapshot.sha(s), "recorded_at": s.get("recorded_at"), "recorded_from": s.get("recorded_from")}
    return {"model": None, "effort": None, "mode": "offline", "prompts": {"ava": "—", "marcus": "—"}, "cases_file": "evals/cases.py",
            "cases_sha": cases_sha(), "snapshots": snaps, "reruns": 0, "command": command}


def run_offline(args: argparse.Namespace, console: Any) -> int:
    """Free checks only; writes evals/results/<run>-offline.json and .html. Exit 1 if anything fails."""
    from evals import offline, report

    tickers = C.PHASE1_TICKERS + (C.PHASE2_TICKERS if args.phase >= 2 else [])
    snapshot_dir = Path(args.snapshots)
    started = datetime.now()
    items = offline.run(tickers, snapshot_dir)
    finished = datetime.now()
    s = offline.summarize(items)
    out = {"run_id": f"{started:%Y-%m-%d-%H%M%S}-offline", "kind": "offline", "started": started.isoformat(timespec="seconds"),
           "finished": finished.isoformat(timespec="seconds"), "duration_s": int((finished - started).total_seconds()),
           "provenance": offline_provenance(tickers, snapshot_dir, "python evals/run_evals.py " + " ".join(sys.argv[1:])),
           "offline": {"summary": s, "items": items}}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{out['run_id']}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    path.with_suffix(".html").write_text(report.render(out, history=report.history(RESULTS_DIR)))
    for it in items:
        if it["status"] != "PASS":
            bad = next((c for c in it["checks"] if c["passed"] is not True), None)
            console.print(f"  {it['status']:6s} {it['id']:20s} {it['title']}" + (f" — {bad['name']}: {bad['observed']}" if bad else ""))
    console.print(f"{s['total'].get('PASS', 0)}/{s['items']} offline checks pass · free · {out['duration_s']} s")
    console.print(f"Saved {path.relative_to(ROOT)} and the report {path.with_suffix('.html').relative_to(ROOT)}")
    return 1 if s["total"].get("FAIL") else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", type=int, default=1, help="1: 5 tickers (default); 2: adds 20 regression tickers")
    ap.add_argument("--suite", help="comma-separated: regression, planted_signal, robustness, pm_synthetic")
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--quick", action="store_true", help="P1 cases only, 1 rerun")
    ap.add_argument("--reruns", type=int, help="default 3 (1 with --quick)")
    ap.add_argument("--workers", type=int, default=4, help="parallel runs (0 = in this process)")
    ap.add_argument("--budget", type=float, help="stop starting runs once this many USD are spent (default 1.5 × estimate)")
    ap.add_argument("--yes", action="store_true", help="required for runs estimated above $2")
    ap.add_argument("--dry-run", action="store_true", help="list the cases and the estimate, run nothing")
    ap.add_argument("--csv", action="store_true", help="export the cases to evals/golden_cases.csv (all) and golden_cases_phase1.csv (5 tickers), then exit")
    ap.add_argument("--offline", action="store_true", help="free checks only (no model): coverage, planted inputs, code guards, dossiers")
    ap.add_argument("--snapshots", default=str(C.SNAPSHOT_DIR), help=argparse.SUPPRESS)
    ap.add_argument("--regrade", metavar="RESULT", help="grade a saved run again with the current graders (free, no model calls)")
    ap.add_argument("--baseline", help="results JSON to compare with (default: the accepted baseline)")
    args = ap.parse_args()

    if args.regrade:
        from datetime import date

        from evals import report

        path = Path(args.regrade)
        result = json.loads(path.read_text())
        changed = regrade(result, date.today().isoformat())
        path.write_text(json.dumps(result, indent=1))
        path.with_suffix(".html").write_text(report.render(result, report.load_baseline(args.baseline), report.history(path.parent)))
        for cid, a, b in changed:
            print(f"  {cid:12} {a} → {b}")
        print(f"Regraded {path.name}: {result['summary']['total'].get('PASS', 0)}/{result['summary']['cases']} pass, {len(changed)} changed.")
        return 0
    if args.csv:
        out, out1 = ROOT / "evals" / "golden_cases.csv", ROOT / "evals" / "golden_cases_phase1.csv"
        print(f"Wrote {export_csv(out)} cases (all 25 tickers) to {out.relative_to(ROOT)}")
        print(f"Wrote {export_csv(out1, phase=1)} cases (Phase 1: NVDA, JPM, KO, TSLA, PFE) to {out1.relative_to(ROOT)}")
        return 0

    from rich.console import Console
    from rich.table import Table

    from evals import offline, report

    console = Console()
    if args.offline:
        return run_offline(args, console)
    reruns = args.reruns or (1 if args.quick else 3)
    selected = select(args.phase, args.suite.split(",") if args.suite else None, args.cases.split(",") if args.cases else None, args.quick)
    snapshot_dir = Path(args.snapshots)
    missing = sorted(t for t in tickers_needed(selected) if not (snapshot_dir / f"{t}.json").exists())
    if missing:
        console.print(f"[red]No snapshot for {', '.join(missing)}.[/red] Record them first (free): python evals/record.py --tickers {','.join(missing)}")
        return 2

    estimate = sum(C.EST_COST[c.kind] for c in selected) * reruns
    budget = args.budget if args.budget is not None else max(1.0, round(estimate * 1.5, 2))
    console.print(f"{len(selected)} cases × {reruns} reruns = {len(selected) * reruns} model runs · estimated ${estimate:.2f} · budget cap ${budget:.2f}")
    if args.dry_run:
        for c in selected:
            console.print(f"  {c.case_id:14s} {c.suite:15s} {c.priority}  {c.title}")
        return 0
    if estimate > 2 and not args.yes:
        console.print("[yellow]Pass --yes to run it.[/yellow]")
        return 2

    console.print("Offline preflight (free)…")
    pre = offline.run(sorted(tickers_needed(selected) | {c.ticker for c in selected if c.kind != "pm"}), snapshot_dir)
    pre_sum = offline.summarize(pre)
    console.print(f"  {pre_sum['total'].get('PASS', 0)}/{pre_sum['items']} offline checks pass" +
                  (f" · [red]{pre_sum['total'].get('FAIL', 0)} fail[/red] (see the report)" if pre_sum["total"].get("FAIL") else ""))
    if offline.blocking(pre):
        console.print(f"[red]Stopping before any model call: snapshot coverage failed for {', '.join(offline.blocking(pre))}.[/red] "
                      "Re-record with evals/record.py --force, then run --offline.")
        return 2

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    policies.set_mode("claude")
    started = datetime.now()
    command = "python evals/run_evals.py " + " ".join(sys.argv[1:])
    prov = provenance(selected, snapshot_dir, reruns, command, "claude")

    def progress(cid: str, run: dict[str, Any], spent: float) -> None:
        if run.get("crash"):
            note = "[red]" + run["crash"][:80] + "[/red]"
        elif run.get("raw") is not None or run.get("final"):
            note = f"raw {(run.get('raw') or {}).get('action')}"
        else:
            note = f"adj {run.get('llm_adjustment', '—')} · {len(run.get('follow_ups', []))} calls"
        console.print(f"  {cid:14s} #{run['rerun']}  {note} · ${run.get('cost', 0):.3f} · total ${spent:.2f}")

    by_case = run_cases(selected, reruns, snapshot_dir, args.workers, budget, progress)
    results = grade_all(selected, by_case)
    finished = datetime.now()
    out = {"run_id": f"{started:%Y-%m-%d-%H%M}", "kind": "online", "started": started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"),
           "duration_s": int((finished - started).total_seconds()), "provenance": prov, "summary": summarize(results), "cases": results,
           "budget_usd": budget, "estimate_usd": round(estimate, 2), "offline": {"summary": pre_sum, "items": pre}}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{out['run_id']}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    baseline = report.load_baseline(args.baseline)
    html = report.render(out, baseline, history=report.history(RESULTS_DIR))
    path.with_suffix(".html").write_text(html)

    table = Table(title=f"Eval {out['run_id']}")
    for col in ("suite", "PASS", "FAIL", "REVIEW", "INVALID", "SKIPPED"):
        table.add_column(col)
    for suite, counts in out["summary"]["by_suite"].items():
        table.add_row(suite, *(str(counts.get(s, 0)) for s in ("PASS", "FAIL", "REVIEW", "INVALID", "SKIPPED")))
    console.print(table)
    s = out["summary"]
    console.print(f"{s['total'].get('PASS', 0)}/{s['cases']} pass · spent ${s['cost']:.2f} · {out['duration_s'] // 60} min")
    console.print(f"Saved {path.relative_to(ROOT)} and the report {path.with_suffix('.html').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
