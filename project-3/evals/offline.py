"""Offline eval checks (D-045): everything that needs no model, on the real snapshots. Free, seconds.

Run on any change:  python evals/run_evals.py --offline
Every online run does these first as a preflight, and stops before spending money if a snapshot is incomplete.

Groups:
  coverage    every tool Ava or Marcus can call finds its data in each snapshot
  planted     each planted change keeps the base score and is visible in exactly the text Ava reads
  guards      the code checks around the model: price sanity, buy floor, grounding, conviction range
  dossiers    every synthetic dossier for Marcus builds and validates
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from evals import cases as C
from nexus import data
from nexus.data import snapshot
from nexus.policies import _sanity_check, format_result
from nexus.schemas import ResearchDossier
from nexus.tools import registry
from nexus.tools import research as tools

GROUPS = [
    ("coverage", "Snapshot coverage", "Every tool Ava or Marcus can call finds its data in each snapshot."),
    ("planted", "Planted changes", "Each change keeps the base score and shows up in the exact text Ava reads."),
    ("guards", "Code guards", "The code checks around the model: price sanity, buy floor, grounding, conviction range."),
    ("dossiers", "Marcus's dossiers", "Every synthetic dossier builds and passes the schema."),
]

RESEARCH_CALLS = [("sec_list_filings", {}), ("sec_get_financials", {"quarters": 1}), ("sec_get_financials", {"quarters": 4}),
                  *[("sec_get_filing_section", {"form": f, "section": s}) for f in snapshot.FORMS for s in snapshot.SECTIONS],
                  *[("sec_get_insider_trades", {"days": d}) for d in snapshot.DAYS],
                  ("get_institutional_holders", {}), ("get_cap_table", {}), ("get_valuation", {}), ("get_price_history", {}), ("compute_technicals", {})]


def _item(group: str, item_id: str, ticker: str, title: str, checks: list[C.Check]) -> dict[str, Any]:
    status = "FAIL" if any(c.passed is False for c in checks) else "REVIEW" if any(c.passed is None for c in checks) else "PASS"
    return {"group": group, "id": item_id, "ticker": ticker, "title": title, "status": status, "checks": [c.__dict__ for c in checks]}


def _guarded(group: str, item_id: str, ticker: str, title: str, fn: Callable[[], list[C.Check]]) -> dict[str, Any]:
    try:
        return _item(group, item_id, ticker, title, fn())
    except Exception as exc:
        return _item(group, item_id, ticker, title, [C.Check("Ran without error", False, f"{type(exc).__name__}: {exc}"[:200], "no exception")])


def _provider(ticker: str, snapshot_dir: Path, patch: C.Patch | None = None) -> snapshot.SnapshotProvider:
    snap = snapshot.load(snapshot_dir / f"{ticker}.json")
    if patch:
        patch(snap["calls"])
    return data.set_provider(snapshot.SnapshotProvider(snap))


def _seen(tool: str, ticker: str, **kw: Any) -> str:
    """What Ava reads for this tool call: the same delimited text the prompt carries."""
    return format_result(registry.call("research_analyst", tool, ticker=ticker, **kw))


def _base(ticker: str) -> float:
    fin, val, tech = tools.sec_get_financials(ticker), tools.get_valuation(ticker), tools.compute_technicals(ticker)
    return tools.compute_scorecard(fin.data, val.data, tech.data).data["base_score"]


def coverage(ticker: str, snapshot_dir: Path) -> list[C.Check]:
    snap = snapshot.load(snapshot_dir / f"{ticker}.json")
    recorded_errors = {v["__error__"] for v in snap["calls"].values() if isinstance(v, dict) and "__error__" in v}
    p = _provider(ticker, snapshot_dir)
    failed = []
    for name, kw in RESEARCH_CALLS:
        try:
            registry.call("research_analyst", name, ticker=ticker, **kw)
        except snapshot.SnapshotMiss:
            pass
        except Exception as exc:
            if str(exc) not in recorded_errors:  # a recorded failure is reported once, by the check below
                failed.append(f"{name}{kw or ''}: {exc}")
    for name, kw in (("compute_correlation_beta", {"holdings": {}}), ("compute_realized_vol", {})):
        try:
            registry.call("portfolio_manager", name, ticker=ticker, **kw)
        except snapshot.SnapshotMiss:
            pass
    errors = [k for k, v in snap["calls"].items() if isinstance(v, dict) and "__error__" in v]
    fin = snap["calls"].get(snapshot.key("financials", 1))
    period = fin.get("period") if isinstance(fin, dict) else None
    age = (int(snap["as_of"][:4]) * 4 + (int(snap["as_of"][5:7]) - 1) // 3) - (int(period[2:6]) * 4 + int(period[7]) - 1) if period else None
    return [
        C.Check("Financials are current", None if age is None else age <= 4, f"latest quarter {period} ({age} quarters before {snap['as_of']})" if period else "no period",
                "within 4 quarters of the snapshot date"),
        C.Check("Every call recorded", not p.misses, f"{len(p.misses)} missing" + (": " + ", ".join(p.misses[:4]) if p.misses else ""), "0 missing"),
        C.Check("No call failed while recording", None if errors else True, ", ".join(errors) or "none",
                "none (a failure replays as a tool error; check it is intended)"),
        C.Check("Every tool runs on it", not failed, "; ".join(failed)[:200] or "all ran", "all ran"),
    ]


# what each planted change must make visible, and where Ava reads it
PROBES: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], str]]] = {
    "1": ("sec_get_insider_trades", {"days": 90}, lambda c: "40 Form 4 filings with sales (0 under 10b5-1 plans)"),
    "2": ("sec_get_insider_trades", {"days": 90}, lambda c: "6 open-market buys"),
    "3": ("sec_get_filing_section", {"form": "10-Q", "section": "risk_factors"}, lambda c: "material weakness"),
    "4": ("sec_get_financials", {"quarters": 1}, lambda c: f'{c[snapshot.key("financials", 1)]["operating_cash_flow_usd_b"]}'),
    "5": ("get_cap_table", {}, lambda c: f'${c[snapshot.key("dilution")]["buyback_usd_b"]:g}B buyback'),
}


def planted(ticker: str, change: C.Change, snapshot_dir: Path) -> list[C.Check]:
    _provider(ticker, snapshot_dir)
    base0 = _base(ticker)
    snap = snapshot.load(snapshot_dir / f"{ticker}.json")
    patched = copy.deepcopy(snap)
    change.patch(patched["calls"])
    changed = patched["calls"] != snap["calls"]
    data.set_provider(snapshot.SnapshotProvider(patched))
    base1 = _base(ticker)
    tool, kw, needle = PROBES[change.code]
    seen = _seen(tool, ticker, **kw)
    want = needle(patched["calls"])
    visible = want.lower() in seen.lower()
    return [
        C.Check("Change applied", changed, "snapshot differs" if changed else "no difference", "snapshot differs"),
        C.Check("Base score unchanged", base0 == base1, f"{base0:.1f} → {base1:.1f}", f"{base0:.1f}"),
        C.Check("Visible to Ava", visible, f'"{want}" ' + ("found" if visible else "not found") + f" in {tool}", f'"{want}" in what she reads'),
        direction(change.code, snap["calls"], patched["calls"]),
    ]


def _ratio(calls: dict[str, Any]) -> float | None:
    f = calls.get(snapshot.key("financials", 1))
    if not isinstance(f, dict) or not f.get("net_income_usd_b") or f.get("operating_cash_flow_usd_b") is None:
        return None
    return f["operating_cash_flow_usd_b"] / f["net_income_usd_b"]


def direction(code: str, before: dict[str, Any], after: dict[str, Any]) -> C.Check:
    """The planted fact must point the way the case claims, compared with the real data it replaces."""
    name = "Points the intended way"
    ins = lambda c, k: (c.get(snapshot.key("insider", 90)) or {}).get(k)  # noqa: E731
    if code == "1":
        b, a = ins(before, "sales"), ins(after, "sales")
        return C.Check(name, (a or 0) > (b or 0), f"insider sales {b} → {a}", "more sales than the real data")
    if code == "2":
        b, a = ins(before, "open_market_buys"), ins(after, "open_market_buys")
        return C.Check(name, (a or 0) > (b or 0), f"open-market buys {b} → {a}", "more buys than the real data")
    if code == "4":
        b, a = _ratio(before), _ratio(after)
        if b is None:
            return C.Check(name, True, f"cash flow not reported before; now {a:.2f}× net income", "weaker cash than the real data")
        return C.Check(name, a < b, f"operating cash flow / net income {b:.2f} → {a:.2f}", "a lower ratio than the real data (weaker cash)")
    if code == "5":
        b = (before.get(snapshot.key("dilution")) or {}).get("buyback_usd_b")
        a = (after.get(snapshot.key("dilution")) or {}).get("buyback_usd_b")
        return C.Check(name, (a or 0) > (b or 0), f"buyback ${b}B → ${a}B", "a bigger buyback")
    return C.Check(name, True, "text inserted", "the flag is new text")


ROB_PROBES = {
    "ROB-01": ("sec_get_insider_trades", {"days": 90}, None),
    "ROB-02": ("sec_get_filing_section", {"form": "10-Q", "section": "risk_factors"}, "not found"),
    "ROB-03": ("sec_get_filing_section", {"form": "10-Q", "section": "risk_factors"}, "strong buy"),
    "ROB-04": ("sec_get_filing_section", {"form": "10-Q", "section": "mda"}, "20 more times"),
    "ROB-05": ("sec_get_insider_trades", {"days": 90}, "0 Form 4 filings with sales"),
    "ROB-06": ("sec_get_financials", {"quarters": 1}, "Gross margin n/a"),
}


def robustness_input(case: C.Case, snapshot_dir: Path) -> list[C.Check]:
    tool, kw, needle = ROB_PROBES[case.case_id]
    _provider(case.ticker, snapshot_dir, case.patch)
    if needle is None:  # the tool must fail, as the case intends
        try:
            registry.call("research_analyst", tool, ticker=case.ticker, **kw)
            return [C.Check("Tool fails as planted", False, "tool returned data", "an error")]
        except Exception as exc:
            return [C.Check("Tool fails as planted", True, f"{type(exc).__name__}: {exc}"[:120], "an error")]
    seen = _seen(tool, case.ticker, **kw)
    return [C.Check("Visible to Ava", needle.lower() in seen.lower(), f'"{needle}" ' + ("found" if needle.lower() in seen.lower() else "not found") + f" in {tool}", f'"{needle}"')]


def conviction_range(ticker: str, snapshot_dir: Path) -> list[C.Check]:
    _provider(ticker, snapshot_dir)
    base = _base(ticker)
    lo, hi = tools.conviction_from(base, -1.5), tools.conviction_from(base, 1.5)
    ok = 0 <= lo <= hi <= 10
    note = f"base {base:.1f}: adjustments −1.5…+1.5 give {lo:.1f}…{hi:.1f}"
    if base - 1.5 < 0:
        note += " (stops at 0)"
    if base + 1.5 > 10:
        note += " (stops at 10)"
    return [C.Check("Every allowed adjustment gives a valid conviction", ok, note, "0.0…10.0")]


def grounding(ticker: str, snapshot_dir: Path) -> list[C.Check]:
    _provider(ticker, snapshot_dir)
    results = [tools.sec_get_financials(ticker), tools.get_valuation(ticker), tools.compute_technicals(ticker)]
    spot = results[2].data["spot"]
    try:
        tools.check_grounding([f"The stock trades at ${spot:.2f}."], results)
        accepted = True
    except tools.GroundingError:
        accepted = False
    try:
        tools.check_grounding(["Gross margin of 54.7% leaves room for 913.4 in buybacks."], results)
        rejected = False
    except tools.GroundingError:
        rejected = True
    return [C.Check("Accepts a number from a tool output", accepted, f"${spot:.2f}", "accepted"),
            C.Check("Rejects invented numbers", rejected, "54.7, 913.4", "rejected")]


def generic_guards() -> list[dict[str, Any]]:
    from nexus.nodes.portfolio_manager import apply_buy_floor

    def sanity() -> list[C.Check]:
        good = _sanity_check({"action": "BUY", "limit_price": 100.5, "stop_loss_price": 91.0, "rationale": ""}, 100.0)
        high = _sanity_check({"action": "BUY", "limit_price": 150.0, "stop_loss_price": 0.0, "rationale": ""}, 100.0)
        tight = _sanity_check({"action": "BUY", "limit_price": 100.0, "stop_loss_price": 99.0, "rationale": ""}, 100.0)
        return [C.Check("A valid BUY passes", good["action"] == "BUY", good["action"], "BUY"),
                C.Check("Limit 50% above spot becomes HOLD", high["action"] == "HOLD", high["action"], "HOLD"),
                C.Check("Stop 1% below limit becomes HOLD", tight["action"] == "HOLD", tight["action"], "HOLD")]

    def floor() -> list[C.Check]:
        below, f1 = apply_buy_floor({"action": "BUY"}, 5.9, 6.0)
        at, f2 = apply_buy_floor({"action": "BUY"}, 6.0, 6.0)
        sell, f3 = apply_buy_floor({"action": "SELL"}, 3.0, 6.0)
        return [C.Check("BUY at 5.9 becomes HOLD", below["action"] == "HOLD" and f1, below["action"], "HOLD"),
                C.Check("BUY at 6.0 stays BUY", at["action"] == "BUY" and not f2, at["action"], "BUY"),
                C.Check("SELL is never floored", sell["action"] == "SELL" and not f3, sell["action"], "SELL")]

    return [_guarded("guards", "GUARD-prices", "all", "Price sanity check (Marcus)", sanity),
            _guarded("guards", "GUARD-floor", "all", "Buy floor (Marcus)", floor)]


def synthetic_dossier(case: C.Case, snapshot_dir: Path, base_cache: dict[str, Any]) -> list[C.Check]:
    from evals.run_evals import base_dossier, pm_dossier

    pm = case.pm
    if pm["base"] not in base_cache:
        _provider(pm["base"], snapshot_dir)
        base_cache[pm["base"]] = base_dossier(pm["base"])
    d = pm_dossier(base_cache[pm["base"]], pm)
    try:
        ResearchDossier.model_validate(d.model_dump())
        valid, why = True, "valid"
    except Exception as exc:
        valid, why = False, str(exc).splitlines()[0][:160]
    return [C.Check("Passes the dossier schema", valid, why, "valid"),
            C.Check("Conviction as planned", d.conviction_score == pm["conviction"], f"{d.conviction_score}", f"{pm['conviction']}"),
            C.Check("Spot price as planned", d.technicals.spot == pm["spot"], f"{d.technicals.spot}", f"{pm['spot']}"),
            _market_cap_check(base_cache[pm["base"]], d)]


def _market_cap_check(base: Any, d: Any) -> C.Check:
    """Price × diluted shares must match the recorded dossier, or Marcus rightly distrusts the price (PM-14)."""
    s0, s1 = base.dilution.diluted_shares_b, d.dilution.diluted_shares_b
    if not (s0 and s1 and base.technicals.spot):
        return C.Check("Market cap unchanged", None, "no share count", "price × shares as recorded")
    before, after = base.technicals.spot * s0, d.technicals.spot * s1
    return C.Check("Market cap unchanged", abs(after / before - 1) < 0.01, f"${after:,.0f}B", f"${before:,.0f}B (±1%)")


def run(tickers: list[str], snapshot_dir: Path, pm_cases: list[C.Case] | None = None, rob_cases: list[C.Case] | None = None) -> list[dict[str, Any]]:
    """All offline checks for these tickers. Restores the fixture provider afterwards."""
    items: list[dict[str, Any]] = []
    try:
        present = [t for t in tickers if (snapshot_dir / f"{t}.json").exists()]
        for t in tickers:
            if t not in present:
                items.append(_item("coverage", f"COV-{t}", t, f"{t} snapshot", [C.Check("Snapshot recorded", False, "no file", f"evals/snapshots/{t}.json")]))
        for t in present:
            items.append(_guarded("coverage", f"COV-{t}", t, f"{t} snapshot", lambda t=t: coverage(t, snapshot_dir)))
        for t in present:
            for ch in C.CHANGES:
                if (t, ch.code) in C.EXCLUDED:
                    continue
                items.append(_guarded("planted", f"PLANT-{t}-{ch.code}", t, f"{t}: {ch.title}", lambda t=t, ch=ch: planted(t, ch, snapshot_dir)))
        for case in rob_cases if rob_cases is not None else C.robustness():
            if case.case_id in ROB_PROBES and case.ticker in present:
                items.append(_guarded("planted", f"INPUT-{case.case_id}", case.ticker, f"{case.case_id}: {case.title}",
                                      lambda case=case: robustness_input(case, snapshot_dir)))
        items += generic_guards()
        for t in present:
            items.append(_guarded("guards", f"RANGE-{t}", t, f"{t}: conviction range", lambda t=t: conviction_range(t, snapshot_dir)))
            items.append(_guarded("guards", f"GROUND-{t}", t, f"{t}: grounding check", lambda t=t: grounding(t, snapshot_dir)))
        cache: dict[str, Any] = {}
        for case in pm_cases if pm_cases is not None else C.pm_cases():
            if case.pm["base"] in present:
                items.append(_guarded("dossiers", f"DOSSIER-{case.case_id}", case.pm["base"], f"{case.case_id}: {case.title}",
                                      lambda case=case: synthetic_dossier(case, snapshot_dir, cache)))
    finally:
        data.use("fixture")
    return items


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, int]] = {}
    for it in items:
        g = by_group.setdefault(it["group"], {})
        g[it["status"]] = g.get(it["status"], 0) + 1
    total: dict[str, int] = {}
    for it in items:
        total[it["status"]] = total.get(it["status"], 0) + 1
    return {"items": len(items), "total": total, "by_group": by_group}


def blocking(items: list[dict[str, Any]]) -> list[str]:
    """Failures that make an online run meaningless: a snapshot that can't serve every call."""
    return [it["id"] for it in items if it["group"] == "coverage" and it["status"] == "FAIL"]


if __name__ == "__main__":  # quick look without the harness
    import sys

    sys.path.insert(0, str(C.ROOT))
    for it in run(C.PHASE1_TICKERS, C.SNAPSHOT_DIR):
        bad = [c for c in it["checks"] if c["passed"] is not True]
        print(f"{it['status']:6s} {it['id']:22s} {it['title']}" + (f"  ← {bad[0]['name']}: {bad[0]['observed']}" if bad else ""))
