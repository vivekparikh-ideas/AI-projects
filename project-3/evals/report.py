"""Render an eval results JSON as a self-contained HTML report (design: evals/report_mock.html).

    python evals/report.py evals/results/<run>.json                 # re-render, compared with the baseline
    python evals/report.py evals/results/<run>.json --baseline <other>.json
    python evals/report.py --accept evals/results/<run>.json        # make it the baseline
    python evals/report.py --review evals/results/<run>.json ROB-08=PASS PM-08=FAIL   # record your verdict on REVIEW cases

The accepted baseline's file name is kept in evals/results/BASELINE.
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals import cases as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
BASELINE_FILE = RESULTS_DIR / "BASELINE"
CSS = (Path(__file__).parent / "report.css").read_text()

SUITES = [
    ("planted_signal", "Ava · planted signals", "Change one fact in a copy of the data. Does Ava notice it, check it and adjust her score?"),
    ("regression", "Ava → Marcus · regression", "Unchanged real data, end to end. Does it complete, stay grounded and give the same answer each time?"),
    ("robustness", "Ava · robustness", "Broken tools, missing data, prompt injections and follow-up questions from Marcus."),
    ("pm_synthetic", "Marcus · synthetic dossiers", "Made-up dossiers that test his rules: the buy floor, SELL only when held, questions, price bands."),
]
_SHORT = {"1": "Insider selling", "2": "Insider buying", "3": "Risk red flag", "4": "Weak cash", "5": "Buyback"}
CHANGE_HEADS = [("C", "Control", "unchanged · spread ≤ 0.3")] + [
    (ch.code, f"{ch.code} · {_SHORT[ch.code]}", C._bound_text(ch.lo, ch.hi).replace("-", "−")) for ch in C.CHANGES]
ATTN_ORDER = {"NEW FAIL": 0, "FAIL": 1, "INVALID": 2, "SKIPPED": 3, "REVIEW": 4}


def e(x: Any) -> str:
    return escape("" if x is None else str(x))


def fmt(x: float | None, signed: bool = True) -> str:
    return "—" if x is None else (f"{x:+.1f}" if signed else f"{x:.1f}").replace("-", "−")


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def load_baseline(path: str | None) -> dict[str, Any] | None:
    if path:
        return load(path)
    if BASELINE_FILE.exists():
        p = RESULTS_DIR / BASELINE_FILE.read_text().strip()
        if p.exists():
            return load(p)
    return None


def history(folder: Path) -> list[dict[str, Any]]:
    rows = []
    for p in sorted(folder.glob("*.json")):
        try:
            r = load(p)
        except (json.JSONDecodeError, OSError):
            continue
        if "provenance" not in r:
            continue
        kind = r.get("kind", "online")
        off = (r.get("offline") or {}).get("summary") or {}
        s = r.get("summary") or {}
        rows.append({"run_id": r["run_id"], "kind": kind, "prompts": r["provenance"]["prompts"], "command": r["provenance"].get("command", ""),
                     "pass": s.get("total", {}).get("PASS", 0) if kind == "online" else 0, "cases": s.get("cases", 0),
                     "off_pass": off.get("total", {}).get("PASS", 0), "off_items": off.get("items", 0),
                     "cost": s.get("cost", 0.0), "reruns": r["provenance"]["reruns"]})
    return rows


# ── comparison ───────────────────────────────────────────────────────────────

def compare(result: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, str]:
    """Per case: 'new' (failing now, passed before), 'fixed', 'same', or 'unseen'."""
    if not baseline or baseline.get("run_id") == result.get("run_id") or result.get("kind") == "offline":
        return {}
    before = {c["case_id"]: c["status"] for c in baseline["cases"]}
    out = {}
    for c in result["cases"]:
        b = before.get(c["case_id"])
        if b is None:
            out[c["case_id"]] = "unseen"
        elif c["status"] == "FAIL" and b in ("PASS", "REVIEW"):
            out[c["case_id"]] = "new"
        elif c["status"] in ("PASS", "REVIEW") and b == "FAIL":
            out[c["case_id"]] = "fixed"
        else:
            out[c["case_id"]] = "same"
    return out


def comparable(result: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    if not baseline or result.get("kind") == "offline":
        return []
    warn = []
    a, b = result["provenance"]["snapshots"], baseline["provenance"]["snapshots"]
    changed = [t for t in a if t in b and a[t]["sha"] != b[t]["sha"]]
    if changed:
        warn.append(f"snapshots re-recorded since the baseline: {', '.join(changed)}")
    if result["provenance"]["cases_sha"] != baseline["provenance"]["cases_sha"]:
        warn.append("cases or thresholds changed since the baseline")
    return warn


def pill(status: str, tag: str = "") -> str:
    if tag == "new":
        return '<span class="pill new">NEW FAIL</span>'
    if tag == "fixed":
        return '<span class="pill fixed">FIXED</span>'
    cls = {"PASS": "pass", "FAIL": "fail", "REVIEW": "review", "INVALID": "invalid", "SKIPPED": "skipped"}.get(status, "review")
    return f'<span class="pill {cls}">{e(status)}</span>'


def first_problem(c: dict[str, Any]) -> str:
    for ch in c["checks"]:
        if ch["passed"] is False:
            return f"{ch['name']}: {ch['observed']} (needed {ch['expected']})"
    for ch in c["checks"]:
        if ch["passed"] is None:
            return f"{ch['name']}: {ch['observed']} ({ch['expected']})"
    if c["status"] == "SKIPPED":
        return "Not run: the budget cap was reached."
    return ""


# ── sections ─────────────────────────────────────────────────────────────────

def _meta(result: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    p, s = result["provenance"], result["summary"]
    snaps = p["snapshots"]
    as_of = sorted({v["as_of"] for v in snaps.values()})
    base = (f'run {e(baseline["run_id"])} · ava {e(baseline["provenance"]["prompts"]["ava"])} · marcus {e(baseline["provenance"]["prompts"]["marcus"])}'
            if baseline and baseline["run_id"] != result["run_id"] else "no baseline yet")
    cells = [
        ("Candidate (this run)", f'<span class="mono">ava {e(p["prompts"]["ava"])} · marcus {e(p["prompts"]["marcus"])}</span>'),
        ("Compared against", f'<span class="mono">{base}</span>'),
        ("Model", f'<span class="mono">{e(p["model"])}' + (f' · effort {e(p["effort"])}' if p.get("effort") else "") + "</span>"),
        ("Input data", f'{len(snaps)} frozen snapshots as of {e(", ".join(as_of))}<br><span class="mono small">'
                       + " · ".join(f'{e(t)} {e(v["sha"])}' for t, v in snaps.items()) + "</span>"),
        ("Cases", f'<span class="mono">{e(p["cases_file"])}</span> · {s["cases"]} cases<br><span class="mono small">sha {e(p["cases_sha"])}</span>'),
        ("Reruns", f'{p["reruns"]} per case · {s["model_runs"]} runs'),
        ("Cost", f'<span class="num">${s["cost"]:.2f}</span> <span class="muted">(estimate ${result.get("estimate_usd", 0):.2f}, cap ${result.get("budget_usd", 0):.2f})</span>'
                 f'<br><span class="small">Ava ${s["cost_ava"]:.2f} · Marcus ${s["cost_marcus"]:.2f} · {s["tokens"]:,} tokens</span>'),
        ("Duration", f'{result["duration_s"] // 60} min {result["duration_s"] % 60} s · started {e(result["started"].replace("T", " "))}'),
        ("Command", f'<span class="mono">{e(p["command"])}</span>'),
    ]
    return '<dl class="meta" style="margin:0">' + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in cells) + "</dl>"


def _verdict(result: dict[str, Any], baseline: dict[str, Any] | None, tags: dict[str, str]) -> str:
    s = result["summary"]
    passed, total = s["total"].get("PASS", 0), s["cases"]
    parts = [f"{passed} of {total} cases pass"]
    if baseline and tags:
        b = baseline["summary"]["total"].get("PASS", 0)
        parts[0] += f", {'up' if passed > b else 'down' if passed < b else 'unchanged'} from {b}" if passed != b else ", the same as the baseline"
    bits = []
    fixed, new = sum(1 for t in tags.values() if t == "fixed"), sum(1 for t in tags.values() if t == "new")
    if tags:
        bits += [f'<span class="up">{fixed} fixed</span>', f'<span class="down">{new} broke</span>']
    for st, word in (("REVIEW", "waiting for your review"), ("INVALID", "invalid (snapshot incomplete)"), ("SKIPPED", "skipped (budget)")):
        if s["total"].get(st):
            bits.append(f'{s["total"][st]} {word}')
    line1 = e(parts[0]) + (". " + ", ".join(bits) + "." if bits else ".")
    if new:
        names = ", ".join(c["case_id"] for c in result["cases"] if tags.get(c["case_id"]) == "new")
        line2 = f"Check the regressions ({e(names)}) before accepting this run as the new baseline."
    elif s["total"].get("FAIL"):
        line2 = "No new failures against the baseline. Open the failing cases below to see what went wrong."
    else:
        line2 = "Nothing failed. Read the REVIEW cases before accepting this run."
    border = "var(--fail)" if new else "var(--review)" if s["total"].get("FAIL") or s["total"].get("REVIEW") else "var(--pass)"
    return (f'<div class="panel verdict" style="border-left-color:{border}"><div class="big">{passed}<small>/{total}</small></div>'
            f'<p class="line1">{line1}</p><p class="muted">{line2}</p></div>')


def _tiles(result: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    out = []
    for key, label, desc in SUITES:
        counts = result["summary"]["by_suite"].get(key)
        if not counts:
            continue
        n = sum(counts.values())
        p, f, r = counts.get("PASS", 0), counts.get("FAIL", 0), counts.get("REVIEW", 0)
        other = n - p - f - r
        delta = ""
        if baseline and baseline["run_id"] != result["run_id"]:
            b = baseline["summary"]["by_suite"].get(key, {}).get("PASS")
            if b is not None:
                delta = (f' <small class="up">▲ {p - b} vs {b}</small>' if p > b else f' <small class="down">▼ {b - p} vs {b}</small>' if p < b
                         else ' <small class="muted">= no change</small>')
        bar = "".join(f'<i class="{c}" style="width:{w / n * 100:.1f}%"></i>' for c, w in (("p", p), ("f", f), ("r", r + other)) if w)
        who = ' style="color:var(--marcus)"' if key == "pm_synthetic" else ""
        out.append(f'<div class="panel tile"><span class="who"{who}>{e(label)}</span><span class="score">{p}<small> / {n} pass</small>{delta}</span>'
                   f'<div class="bar">{bar}</div><p class="desc">{e(desc)}</p></div>')
    return '<div class="tiles">' + "".join(out) + "</div>"


def _attention(result: dict[str, Any], tags: dict[str, str]) -> str:
    rows = []
    for c in result["cases"]:
        if c["status"] == "PASS":
            continue
        label = "NEW FAIL" if tags.get(c["case_id"]) == "new" else c["status"]
        before = {"same": " Also failed in the baseline.", "unseen": " Not in the baseline."}.get(tags.get(c["case_id"], ""), "") if c["status"] == "FAIL" else ""
        if tags.get(c["case_id"]) == "new":
            before = " Passed in the baseline."
        rows.append((ATTN_ORDER.get(label, 5), c["case_id"],
                     f'<div class="row"><span>{pill(c["status"], tags.get(c["case_id"], "") if label == "NEW FAIL" else "")}</span>'
                     f'<span class="mono"><a href="#{e(c["case_id"])}">{e(c["case_id"])}</a></span><div class="what">{e(c["title"])}'
                     f'<span>{e(first_problem(c))}{e(before)}</span></div></div>'))
    if not rows:
        return '<div class="panel empty">Every case passed.</div>'
    return '<div class="panel attn">' + "".join(r for _, _, r in sorted(rows, key=lambda x: (x[0], x[1]))) + "</div>"


def _grid(result: dict[str, Any], baseline: dict[str, Any] | None, tags: dict[str, str]) -> str:
    sig = {c["case_id"]: c for c in result["cases"] if c["suite"] == "planted_signal"}
    if not sig:
        return ""
    before = {c["case_id"]: c for c in baseline["cases"]} if baseline else {}
    tickers = list(dict.fromkeys(c["ticker"] for c in sig.values()))
    cells = ['<div class="h">Ticker</div>'] + [f'<div class="h">{e(t)}<b>{e(r)}</b></div>' for _, t, r in CHANGE_HEADS]
    for t in tickers:
        ctrl = sig.get(f"SIG-{t}-C")
        base = ctrl["metrics"].get("base") if ctrl else None
        cells.append(f'<div class="t">{e(t)}<span>base {fmt(base, False)}</span></div>')
        for code, _, _ in CHANGE_HEADS:
            c = sig.get(f"SIG-{t}-{code}")
            if not c:
                cells.append('<div class="cell"><span class="n">not run</span></div>')
                continue
            m, cls = c["metrics"], "pass" if c["status"] == "PASS" else "fail" if c["status"] == "FAIL" else ""
            if code == "C":
                main, notes = fmt(m.get("median_adj")), f'median adj · spread {fmt(m.get("spread"), False)}'
            else:
                main = fmt(m.get("delta"))
                notes = " · ".join(x for x in (f'opened {m["opened"]}' if m.get("opened") else "", f'named {m["named"]}' if m.get("named") else "") if x)
            was = ""
            tag = tags.get(c["case_id"])
            prev = before.get(c["case_id"])
            if tag in ("new", "fixed") and prev:
                pm_ = prev["metrics"].get("median_adj" if code == "C" else "delta")
                was = f'<span class="was {"down" if tag == "new" else "up"}">{"new" if tag == "new" else "fixed"} · was {fmt(pm_)}</span>'
            if c["status"] in ("INVALID", "SKIPPED", "REVIEW"):
                notes = (notes + " · " if notes else "") + c["status"].lower()
            cells.append(f'<div class="cell {cls}"><a class="d" href="#{e(c["case_id"])}" style="color:inherit;text-decoration:none">{main}</a>'
                         f'<span class="n">{e(notes)}</span>{was}</div>')
    return ('<div class="panel tbl"><div class="grid">' + "".join(cells) + "</div></div>"
            '<p class="small">Each cell is Ava\'s median adjustment on the changed copy minus her median on the unchanged copy. '
            '"Opened" means she called the tool that shows the planted fact; "named" means her text mentions it. '
            "Weak cash is in her starting data, so there is no tool to open.</p>")


def _table(head: list[str], rows: list[tuple[str, list[str]]]) -> str:
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    body = "".join(f'<tr class="{cls}">' + "".join(f"<td>{v}</td>" for v in vals) + "</tr>" for cls, vals in rows)
    return f'<div class="panel tbl"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _row_class(c: dict[str, Any]) -> str:
    return "bad" if c["status"] == "FAIL" else "rev" if c["status"] in ("REVIEW", "INVALID") else ""


def _link(c: dict[str, Any]) -> str:
    return f'<a class="mono" href="#{e(c["case_id"])}">{e(c["case_id"])}</a>'


def _regression(result: dict[str, Any], tags: dict[str, str]) -> str:
    rows = []
    for c in result["cases"]:
        if c["suite"] != "regression":
            continue
        m, runs = c["metrics"], c["runs"]
        ok = sum(1 for r in runs if r.get("dossier_ok"))
        rows.append((_row_class(c), [
            _link(c), f"{ok}/{len(runs)}", e(m.get("repairs", "—")), f'<span class="mono">{" · ".join(map(str, m.get("follow_up_counts", [])))}</span>',
            e(m.get("duplicates", "—")), f'<span class="mono">{e(" ".join(str(a or "—") for a in m.get("actions", [])))}</span>',
            f'<span class="mono">{" · ".join(f"{x:.1f}" for x in m.get("convictions", []))}</span>', f'<span class="mono">{fmt(m.get("spread"), False)}</span>',
            f'<span class="mono">${c["cost"]:.2f}</span>', pill(c["status"], tags.get(c["case_id"], ""))]))
    if not rows:
        return ""
    return _table(["Case", "Completed", "Repairs", "Follow-ups", "Repeated calls", "Marcus actions", "Conviction", "Spread", "Cost", "Status"], rows)


def _check_list(c: dict[str, Any]) -> str:
    marks = {True: '<span class="up">✓</span>', False: '<span class="down">✗</span>', None: '<span style="color:var(--review)">?</span>'}
    return "<br>".join(f'{marks[ch["passed"]]} {e(ch["name"])}: <span class="mono small">{e(ch["observed"])}</span>' for ch in c["checks"])


def _robustness(result: dict[str, Any], tags: dict[str, str]) -> str:
    rows = [(_row_class(c), [_link(c), e(c["ticker"]), f'{e(c["title"])}<br><span class="small">{e(c["planted_value"])}</span>',
                             _check_list(c), pill(c["status"], tags.get(c["case_id"], ""))])
            for c in result["cases"] if c["suite"] == "robustness"]
    return _table(["Case", "Ticker", "What we did", "Checks (all runs)", "Status"], rows) if rows else ""


def _marcus(result: dict[str, Any], tags: dict[str, str]) -> str:
    rows = []
    for c in result["cases"]:
        if c["suite"] != "pm_synthetic":
            continue
        pm, m = c["pm"], c["metrics"]
        held = "no fund" if pm.get("held") is None else (f'{pm["held"]:g}%' if pm["held"] else "—")
        raw = " ".join("ASK" if a == "NEED_MORE_RESEARCH" else str(a or "—") for a in m.get("raw_actions", []))
        final = " ".join("ASK" if a == "NEED_MORE_RESEARCH" else str(a or "—") for a in m.get("final_actions", []))
        if any(m.get("floored", [])):
            final += ' <span class="small">(floor applied by code)</span>'
        prices = " · ".join("0 / 0" if not lim else f"{lim:,.2f} / {stop or 0:,.2f}" for lim, stop in m.get("prices", []))
        q = next((x for x in m.get("questions", []) if x), "")
        if q:
            prices += f'<br><span class="small">"{e(q)}"</span>'
        rows.append((_row_class(c), [_link(c), e(c["title"]), f'<span class="mono">{pm.get("conviction")}</span>', e(held),
                                     f'<span class="mono">${pm.get("spot", 0):,.2f}</span>', "yes" if pm.get("question_allowed") else "no",
                                     f'<span class="mono">{pm.get("floor")}</span>', e(c["expected"]), f'<span class="mono">{e(raw)}</span>',
                                     f'<span class="mono">{final}</span>', f'<span class="mono">{prices}</span>', pill(c["status"], tags.get(c["case_id"], ""))]))
    if not rows:
        return ""
    return (_table(["Case", "Setup", "Conv.", "Held", "Spot", "Can ask", "Floor", "Expected", "Raw (each run)", "Final", "Prices (limit / stop)", "Status"], rows)
            + '<p class="small">ASK = NEED_MORE_RESEARCH. "Raw" is Marcus\'s answer before code applies the price check and the buy floor; cases are graded on it.</p>')


def _detail(c: dict[str, Any], tags: dict[str, str], open_: bool) -> str:
    kv = []
    if c["field_changed"] not in ("none", ""):
        kv.append(("What we changed", f'{e(c["field_changed"])}<br><span class="small">{e(c["planted_value"])}</span>'))
    else:
        kv.append(("Setup", e(c["setup"])))
    if c.get("question"):
        kv.append(("PM question", e(c["question"])))
    kv.append(("Expected", e(c["expected"])))
    if c.get("control"):
        kv.append(("Compared with", f'<a class="mono" href="#{e(c["control"])}">{e(c["control"])}</a>'))
    if c.get("manual_review"):
        kv.append(("For you to judge", e(c["manual_review"])))
    if c.get("review"):
        r = c["review"]
        kv.append(("Your verdict", f'{e(r["verdict"])} on {e(r["date"])} (code graded it {e(r["was"])})'))
    kvs = '<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv) + "</dl>"

    if c["suite"] == "pm_synthetic":
        head = ["Run", "Raw action", "Limit / stop", "Question", "Final", "Rationale"]
        rows = []
        for r in c["runs"]:
            raw = r.get("raw") or {}
            rows.append(("", [f'<span class="mono">{r["rerun"]}</span>', f'<span class="mono">{e(raw.get("action", "—"))}</span>',
                              f'<span class="mono">{raw.get("limit_price", 0) or 0:,.2f} / {raw.get("stop_loss_price", 0) or 0:,.2f}</span>',
                              f'<span class="small">{e(raw.get("question", ""))}</span>', f'<span class="mono">{e((r.get("final") or {}).get("action", "—"))}</span>',
                              f'<span class="small">{e(raw.get("rationale", "") or r.get("crash", ""))}</span>']))
    else:
        head = ["Run", "Follow-up calls", "Adj.", "Conv.", "Cost"]
        rows = []
        for r in c["runs"]:
            calls = " · ".join(s["tool"].replace("sec_get_", "").replace("get_", "") + (f'({",".join(str(v) for v in s["args"].values())})' if s["args"] else "")
                               for s in r.get("follow_ups", []))
            if r.get("round2_follow_ups") is not None:
                calls += ' <span class="muted">| round 2:</span> ' + e(" · ".join(s["tool"].replace("sec_get_", "") for s in r["round2_follow_ups"]) or "none")
            note = r.get("crash") or r.get("skipped") or r.get("error_note") or ""
            rows.append(("", [f'<span class="mono">{r["rerun"]}</span>', f'<span class="mono small">{calls or "none"}</span>' + (f'<br><span class="small down">{e(note)}</span>' if note else ""),
                              f'<span class="mono">{fmt(r.get("llm_adjustment"))}</span>', f'<span class="mono">{fmt(r.get("conviction"), False)}</span>',
                              f'<span class="mono">${r.get("cost", 0) or 0:.3f}</span>']))
    runs = "<table style=\"min-width:0\"><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>" + \
           "".join("<tr>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>" for _, vals in rows) + "</tbody></table>"
    checks = '<table class="checks" style="min-width:0"><thead><tr><th>Check</th><th>Observed</th><th>Needed</th><th></th></tr></thead><tbody>' + "".join(
        f'<tr><td>{e(ch["name"])}</td><td class="mono">{e(ch["observed"])}</td><td class="mono small">{e(ch["expected"])}</td>'
        f'<td>{pill("PASS" if ch["passed"] else "FAIL" if ch["passed"] is False else "REVIEW")}</td></tr>' for ch in c["checks"]) + "</tbody></table>"
    quotes = []
    first = next((r for r in c["runs"] if r.get("bear_case") or r.get("note") or (r.get("raw") or {}).get("rationale")), None)
    if first:
        if first.get("bear_case"):
            quotes.append(f'<blockquote>Run {first["rerun"]} bear case: "{e(first["bear_case"])}"<br>Why adjusted: "{e(first.get("adjustment_reason", ""))}"</blockquote>')
        if first.get("note"):
            quotes.append(f'<blockquote>Run {first["rerun"]} note to Marcus: "{e(first["note"])}"</blockquote>')
    return (f'<details class="case" id="{e(c["case_id"])}"{" open" if open_ else ""}><summary>{pill(c["status"], tags.get(c["case_id"], ""))}'
            f'<span class="mono">{e(c["case_id"])}</span><span class="muted">{e(c["title"])}</span>'
            f'<span class="small" style="margin-left:auto">${c["cost"]:.3f}</span></summary>'
            f'<div class="detail">{kvs}<div class="tbl">{runs}</div>{checks}{"".join(quotes)}</div></details>')


def _history(rows: list[dict[str, Any]], current: str, baseline_id: str | None) -> str:
    if not rows:
        return ""
    body = []
    for h in rows[-12:]:
        note = "This run" if h["run_id"] == current else "Accepted baseline" if h["run_id"] == baseline_id else ""
        cls = "" if h["run_id"] == current else "dim"
        online = h.get("kind", "online") == "online"
        if online:
            pct = h["pass"] / h["cases"] * 100 if h["cases"] else 0
            rate = f'<span class="hist-bar {cls}" style="width:{pct:.0f}px"></span>{h["pass"]}/{h["cases"]} cases · {pct:.0f}%'
        else:
            pct = h["off_pass"] / h["off_items"] * 100 if h.get("off_items") else 0
            rate = f'<span class="hist-bar {cls}" style="width:{pct:.0f}px"></span>{h["off_pass"]}/{h["off_items"]} checks · {pct:.0f}%'
        mode = (f'{h["reruns"]} reruns · ' if online else "") + (h["command"].replace("python evals/run_evals.py", "").strip() or "default")
        body.append(("", [f'<span class="mono">{"<b>" if note == "This run" else ""}{e(h["run_id"])}{"</b>" if note == "This run" else ""}</span>',
                          '<span class="pill review">ONLINE</span>' if online else '<span class="pill pass">OFFLINE</span>',
                          f'<span class="mono">ava {e(h["prompts"]["ava"])} · marcus {e(h["prompts"]["marcus"])}</span>' if online else '<span class="muted">no model</span>',
                          f'<span class="small">{e(mode)}</span>', f'<span class="mono">{rate}</span>',
                          f'<span class="mono">${h["cost"]:.2f}</span>' if online else '<span class="mono">free</span>', e(note)]))
    return _table(["Run", "Type", "Prompts", "Mode", "Pass rate", "Cost", "Note"], body)


OFFLINE_GROUPS = [
    ("coverage", "Snapshot coverage", "Every tool Ava or Marcus can call finds its data in each snapshot."),
    ("planted", "Planted inputs", "Each change keeps the base score, shows up in the text Ava reads and points the intended way."),
    ("guards", "Code guards", "The code checks around the model: price sanity, buy floor, grounding, conviction range."),
    ("dossiers", "Marcus's dossiers", "Every synthetic dossier builds and passes the schema."),
]


def _offline_section(off: dict[str, Any] | None, preflight: bool) -> str:
    if not off:
        return '<div class="panel empty">No offline checks in this results file.</div>'
    items, s = off["items"], off["summary"]
    tiles = []
    for key, label, desc in OFFLINE_GROUPS:
        counts = s["by_group"].get(key)
        if not counts:
            continue
        n = sum(counts.values())
        p, f = counts.get("PASS", 0), counts.get("FAIL", 0)
        r = n - p - f
        bar = "".join(f'<i class="{c}" style="width:{w / n * 100:.1f}%"></i>' for c, w in (("p", p), ("f", f), ("r", r)) if w)
        tiles.append(f'<div class="panel tile"><span class="who">{e(label)}</span><span class="score">{p}<small> / {n} pass</small></span>'
                     f'<div class="bar">{bar}</div><p class="desc">{e(desc)}</p></div>')
    problems = [it for it in items if it["status"] != "PASS"]
    rows = []
    for it in problems:
        bad = next((c for c in it["checks"] if c["passed"] is not True), None)
        rows.append(f'<div class="row"><span>{pill(it["status"])}</span><span class="mono">{e(it["id"])}</span><div class="what">{e(it["title"])}'
                    f'<span>{e(bad["name"] + ": " + bad["observed"] + " (needed " + bad["expected"] + ")") if bad else ""}</span></div></div>')
    attn = ('<div class="panel attn">' + "".join(rows) + "</div>") if rows else '<div class="panel empty">Every offline check passed.</div>'
    full = "".join(
        f'<tr class="{"bad" if it["status"] == "FAIL" else "rev" if it["status"] == "REVIEW" else ""}"><td class="mono">{e(it["id"])}</td><td>{e(it["title"])}</td>'
        f'<td>{_check_list(it)}</td><td>{pill(it["status"])}</td></tr>' for it in items)
    note = ("Run before every online eval. A coverage failure stops the run before any model call; other failures are shown and the run goes on."
            if preflight else "Run on any change: python evals/run_evals.py --offline. Free, no model calls.")
    return (f'<p class="small">{e(note)}</p><div class="tiles">{"".join(tiles)}</div>'
            f'<h3>Offline problems</h3>{attn}'
            f'<details class="panel"><summary class="empty" style="cursor:pointer">All {len(items)} offline checks</summary>'
            f'<div class="tbl"><table><thead><tr><th>Check</th><th>What</th><th>Results</th><th>Status</th></tr></thead><tbody>{full}</tbody></table></div></details>')


def _split(result: dict[str, Any]) -> str:
    off = (result.get("offline") or {}).get("summary")
    on = result.get("summary") if result.get("kind", "online") == "online" else None

    def panel(title: str, sub: str, passed: int | None, total: int | None, fails: int, href: str) -> str:
        if passed is None:
            body = '<p class="muted">Not run in this report.</p>'
            border = "var(--line2)"
        else:
            body = f'<div class="big" style="font-size:28px;font-weight:700">{passed}<small style="font-size:14px;color:var(--muted)">/{total} pass</small></div>'
            border = "var(--fail)" if fails else "var(--pass)"
        return (f'<a href="{href}" class="panel" style="display:grid;gap:6px;padding:14px 16px;border-left:3px solid {border};text-decoration:none;color:inherit">'
                f'<span class="who" style="font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">{e(title)}</span>{body}'
                f'<span class="small">{e(sub)}</span></a>')

    return ('<div class="tiles">'
            + panel("Part 1 · Offline checks", "Free, no model. Tests the inputs and the code around the models.",
                    off["total"].get("PASS", 0) if off else None, off["items"] if off else None, off["total"].get("FAIL", 0) if off else 0, "#offline")
            + panel("Part 2 · Online evals", "Claude, paid. Tests Ava's and Marcus's judgement on the frozen data.",
                    on["total"].get("PASS", 0) if on else None, on["cases"] if on else None, on["total"].get("FAIL", 0) if on else 0, "#online")
            + "</div>")


def _offline_meta(result: dict[str, Any]) -> str:
    p = result["provenance"]
    snaps = p["snapshots"]
    cells = [
        ("Input data", f'{len(snaps)} frozen snapshots<br><span class="mono small">' + " · ".join(f'{e(t)} {e(v["sha"])} ({e(v["as_of"])})' for t, v in snaps.items()) + "</span>"),
        ("Cases", f'<span class="mono">{e(p["cases_file"])}</span><br><span class="mono small">sha {e(p["cases_sha"])}</span>'),
        ("Cost", "free · no model calls"),
        ("Duration", f'{result["duration_s"]} s · started {e(result["started"].replace("T", " "))}'),
        ("Command", f'<span class="mono">{e(p["command"])}</span>'),
    ]
    return '<dl class="meta" style="margin:0">' + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in cells) + "</dl>"


# ── findings-first layout (plain words) ──────────────────────────────────────

CHANGE_WORDS = {"1": "insider selling", "2": "insider buying", "3": "a red flag in Risk Factors", "4": "weak cash", "5": "a bigger buyback"}
CHANGE_DID = {"1": "Changed the data to show executives sold stock 40 times in 90 days, none pre-scheduled.",
              "2": "Changed the data to show executives bought stock 6 times with their own money.",
              "3": "Added to Risk Factors: a material weakness in accounting controls and an SEC investigation into revenue.",
              "4": "Changed the data so only 40% of profit arrives as cash, and receivables grow 40 points faster than sales.",
              "5": "Doubled the money the company spends buying back its own shares."}
def _want(ch: Any) -> str:
    if ch.lo is not None and ch.hi is not None:
        return f"Stay calm: move between {fmt(ch.lo)} and {fmt(ch.hi)}"
    word, size = ("Raise", ch.lo) if ch.lo is not None else ("Lower", -ch.hi)
    return ("Open Risk Factors, find it, " + word.lower() if ch.code == "3" else word) + f" her score by {size:.1f} or more"


CHANGE_WANT = {ch.code: _want(ch) for ch in C.CHANGES}
TOOL_WORDS = {"insider trades": "insider trades", "filing section (risk factors)": "Risk Factors"}


def _ticks(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _check(c: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    return next((ch for ch in c["checks"] if ch["name"].startswith(prefix)), None)


def _planted_reason(c: dict[str, Any]) -> str:
    """Why a planted case failed, in one plain phrase."""
    opened = _check(c, "Opened")
    named = _check(c, "Names")
    delta = next((ch for ch in c["checks"] if ch["name"].startswith("Δ") or "≤ Δ ≤" in ch["name"]), None)
    m = c["metrics"]
    if opened and opened["passed"] is False:
        what = opened["name"].replace("Opened ", "")
        return f"never opened {TOOL_WORDS.get(what, what)}" if opened["observed"].startswith("0/") else f"opened {TOOL_WORDS.get(what, what)} in only {opened['observed']} runs"
    if delta and delta["passed"] is False:
        d = m.get("delta")
        if c["case_id"].endswith("-5"):
            return "overreacted" if d is not None and d > 0 else "moved the wrong way"
        if named and named["passed"] is False:
            return "didn't mention it and barely moved"
        return "saw it but barely changed her score"
    if named and named["passed"] is False:
        return "didn't mention it"
    if c["status"] == "INVALID":
        return "the data snapshot was incomplete"
    return first_problem(c)


def _findings(result: dict[str, Any]) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    cases = result["cases"]
    off = (result.get("offline") or {}).get("summary")
    sig = [c for c in cases if c["suite"] == "planted_signal"]
    # Ava: one line per planted change
    for code, words in CHANGE_WORDS.items():
        group = [c for c in sig if c["case_id"].endswith(f"-{code}")]
        if not group:
            continue
        ok = [c["ticker"] for c in group if c["status"] == "PASS"]
        bad = [c for c in group if c["status"] not in ("PASS", "SKIPPED")]
        if not bad:
            out.append((True, f"Ava reacted to {words} for all {len(group)} stocks."))
            continue
        by_reason: dict[str, list[str]] = {}
        for c in bad:
            by_reason.setdefault(_planted_reason(c), []).append(c["ticker"])
        parts = [f"{reason} for {_ticks(ts)}" for reason, ts in by_reason.items()]
        tail = f" She got it right for {_ticks(ok)}." if ok else ""
        out.append((False, f"{words[0].upper() + words[1:]}: Ava " + "; ".join(parts) + f".{tail}"))
    controls = [c for c in sig if c["case_id"].endswith("-C")]
    if controls:
        spreads = [c["metrics"].get("spread") or 0 for c in controls]
        unstable = [c["ticker"] for c in controls if c["status"] == "FAIL"]
        out.append((not unstable, f"Ava is consistent: the same stock gets nearly the same score every run (largest spread {max(spreads):.2f})." if not unstable
                    else f"Ava's normal score wobbles between runs for {_ticks(unstable)}, so their planted results are less reliable."))
    reg = [c for c in cases if c["suite"] == "regression"]
    if reg:
        bad = [c for c in reg if c["status"] != "PASS"]
        out.append((not bad, f"End to end, all {len(reg)} stocks finished with the same decision every run." if not bad
                    else f"End to end, {_ticks([c['ticker'] for c in bad])} had problems: " + "; ".join(first_problem(c) for c in bad) + "."))
    rob = [c for c in cases if c["suite"] == "robustness"]
    if rob:
        bad = [c for c in rob if c["status"] == "FAIL"]
        out.append((not bad, "Ava handled broken tools, missing data and trick instructions hidden in filings." if not bad
                    else "Ava had trouble with: " + "; ".join(f"{c['title'].lower()} ({first_problem(c)})" for c in bad) + "."))
    pm = [c for c in cases if c["suite"] == "pm_synthetic"]
    if pm:
        bad = [c for c in pm if c["status"] == "FAIL"]
        good = sum(1 for c in pm if c["status"] == "PASS")
        out.append((not bad, f"Marcus followed his rules in {good} of {len(pm)} tests" + ("." if not bad else ". Failed: " + "; ".join(
            f"{c['case_id']} {c['title'].lower()} (he chose {' '.join(str(a) for a in c['metrics'].get('raw_actions', []))}: "
            f"\"{((c['runs'][0].get('raw') or {}).get('rationale') or '')[:140].rstrip()}…\")" for c in bad) + ".")))
    if off:
        f = off["total"].get("FAIL", 0)
        out.append((not f, f"All {off['items']} offline checks passed: the data and the code around the models are sound." if not f
                    else f"{f} of {off['items']} offline checks failed (see Offline checks below)."))
    return out


def _quote(c: dict[str, Any]) -> str:
    r = c["runs"][0] if c["runs"] else {}
    text = (r.get("raw") or {}).get("rationale") or r.get("note") or r.get("adjustment_reason") or ""
    return text[:260].rstrip() + ("…" if len(text) > 260 else "")


def _todos(result: dict[str, Any], baseline: dict[str, Any] | None, tags: dict[str, str], path_hint: str) -> list[str]:
    items = []
    for c in result["cases"]:
        if tags.get(c["case_id"]) == "new":
            items.append(f"<b>{e(c['case_id'])}</b> passed before and fails now: {e(first_problem(c))}")
    for c in result["cases"]:
        if c["status"] == "REVIEW":
            ask = next((ch["expected"] for ch in c["checks"] if ch["passed"] is None), "")
            items.append(f"<b>{e(c['case_id'])} · {e(c['title'])}</b>: pass or fail? <span class='muted'>({e(ask)})</span>"
                         f"<blockquote>{e(_quote(c))}</blockquote>")
    for st, why in (("INVALID", "asked for data the snapshot doesn't have: re-record it"), ("SKIPPED", "not run: the budget cap was reached")):
        ids = [c["case_id"] for c in result["cases"] if c["status"] == st]
        if ids:
            items.append(f"{len(ids)} case{'s' if len(ids) > 1 else ''} {why}: {e(', '.join(ids))}")
    if not (baseline and baseline.get("run_id") == result["run_id"]):
        items.append(f"If you agree with the results, accept this run as the baseline so later runs are compared with it: "
                     f"<span class='mono'>python evals/report.py --accept {e(path_hint)}</span>")
    return items


def _plain_rows(c: dict[str, Any]) -> tuple[str, str, str]:
    """(we did, we expected, what happened) in plain words."""
    m, suite = c["metrics"], c["suite"]
    if suite == "planted_signal":
        code = c["case_id"].rsplit("-", 1)[1]
        if code == "C":
            return ("Nothing: her normal score for this stock.", "The same score every run.",
                    f"Normal adjustment {fmt(m.get('median_adj'))}; runs differ by {m.get('spread') or 0:.2f}.")
        got = f"Score moved {fmt(m.get('delta'))} vs normal"
        extra = [f"opened the data {m['opened']}" for _ in [0] if m.get("opened")] + [f"mentioned it {m['named']}" for _ in [0] if m.get("named")]
        got += (" · " + " · ".join(extra) if extra else "") + "."
        if c["status"] == "FAIL":
            got += f" <b>{e(_planted_reason(c)[0].upper() + _planted_reason(c)[1:])}.</b>"
        need = m.get("needed") or ""
        want = CHANGE_WANT[code] + (f" <span class='muted'>(adjusted for her ±1.5 limit: {e(need)})</span>" if need and "left" in str(need) else "")
        return (e(CHANGE_DID[code]), want, got)
    if suite == "regression":
        acts = " ".join(str(a or "—") for a in m.get("actions", []))
        convs = ", ".join(f"{x:.1f}" for x in m.get("convictions", []))
        got = f"Marcus said {acts}; conviction {convs}."
        if c["status"] != "PASS":
            got += f" <b>{e(first_problem(c))}</b>"
        return ("Ran the real data end to end, no changes.", "A grounded dossier and the same decision every run.", got)
    if suite == "robustness":
        got = "As expected." if c["status"] == "PASS" else f"<b>{e(first_problem(c))}</b>"
        if c["status"] == "REVIEW":
            got = "Needs your judgement (see to-do)."
        return (e(c["planted_value"] if c["planted_value"] != "—" else c["title"]), e(c["expected"]), got)
    pm = c["pm"]
    held = "no fund" if pm.get("held") is None else (f"holds {pm['held']:g}%" if pm["held"] else "not held")
    did = f"Conviction {pm.get('conviction')}, price ${pm.get('spot', 0):,.2f}, {held}" + (", may ask a question" if pm.get("question_allowed") else "") + f". {e(c['title'])}."
    acts = " ".join("ASK" if a == "NEED_MORE_RESEARCH" else str(a or "—") for a in m.get("raw_actions", []))
    got = f"He chose {acts}." + ("" if c["status"] == "PASS" else " Needs your judgement (see to-do)." if c["status"] == "REVIEW" else f" <b>{e(first_problem(c))}</b>")
    return (did, e(c["expected"]), got)


def _plain_tests(result: dict[str, Any], tags: dict[str, str]) -> str:
    groups = [("planted_signal", "Ava · planted facts", "We secretly change one fact in a copy of a stock's data and check that Ava reacts. 'Normal' is her score on the unchanged copy."),
              ("regression", "Ava → Marcus · real data", "The unchanged data, end to end."),
              ("robustness", "Ava · when things go wrong", "Broken tools, missing data, trick instructions, follow-up questions."),
              ("pm_synthetic", "Marcus · his rules", "Made-up dossiers that test one rule each. Graded on his own answer, before code checks it.")]
    order = {"FAIL": 0, "INVALID": 1, "REVIEW": 2, "SKIPPED": 3, "PASS": 4}
    mark = {"PASS": '<span class="up">✓</span>', "FAIL": '<span class="down">✗</span>', "REVIEW": '<span style="color:var(--review)">?</span>'}
    out = []
    for key, title, sub in groups:
        cs = sorted([c for c in result["cases"] if c["suite"] == key], key=lambda c: (order.get(c["status"], 5), c["case_id"]))
        if not cs:
            continue
        passed = sum(1 for c in cs if c["status"] == "PASS")
        rows = "".join(
            f'<tr class="{_row_class(c)}"><td>{mark.get(c["status"], "·")}</td><td><a class="mono" href="#{e(c["case_id"])}">{e(c["case_id"])}</a>'
            f'{" " + pill(c["status"], "new") if tags.get(c["case_id"]) == "new" else ""}<br><span class="small">{e(c["title"])}</span></td>'
            + "".join(f"<td>{v}</td>" for v in _plain_rows(c)) + "</tr>" for c in cs)
        out.append(f'<details class="panel"{" open" if any(c["status"] != "PASS" for c in cs) else ""}><summary class="empty" style="cursor:pointer">'
                   f'<b style="color:var(--ink)">{e(title)}</b> · {passed} of {len(cs)} pass <span class="small">· {e(sub)}</span></summary>'
                   f'<div class="tbl"><table><thead><tr><th></th><th>Test</th><th>What we did</th><th>What we expected</th><th>What happened</th></tr></thead>'
                   f"<tbody>{rows}</tbody></table></div></details>")
    return "".join(out)


def _render_findings_first(result: dict[str, Any], baseline: dict[str, Any] | None, history_rows: list[dict[str, Any]] | None, head: str, tail: str) -> str:
    tags = compare(result, baseline)
    warns = comparable(result, baseline)
    p, s = result["provenance"], result["summary"]
    off = (result.get("offline") or {}).get("summary")
    is_base = baseline is not None and baseline.get("run_id") == result["run_id"]
    when = result["started"][:10]
    chips = [f'<span class="chip">ava {e(p["prompts"]["ava"])} · marcus {e(p["prompts"]["marcus"])}</span>']
    if p["mode"] != "claude":
        chips.insert(0, '<span class="chip mock">SCRIPTED · offline test, no model calls</span>')
    chips.append('<span class="chip ok">Accepted baseline</span>' if is_base else '<span class="chip pending">Not yet accepted</span>')
    chips += [f'<span class="chip warn">{e(w)}</span>' for w in warns]

    passed, total = s["total"].get("PASS", 0), s["cases"]
    vs = ""
    if tags:
        b = baseline["summary"]["total"].get("PASS", 0)
        vs = f'<span class="small">{"▲" if passed > b else "▼" if passed < b else "="} vs {b} before</span>'
    nums = [
        (f"{passed}/{total}", "tests pass", vs),
        (f"{off['total'].get('PASS', 0)}/{off['items']}" if off else "—", "offline checks pass", '<span class="small">free, no model</span>'),
        (f"${s['cost']:.2f}", "spent", f'<span class="small">{result["duration_s"] // 60} min · {s["model_runs"]} model runs</span>'),
    ]
    big = "".join(f'<div class="panel tile"><span class="score" style="font-size:30px">{v}</span><span class="who">{e(k)}</span>{x}</div>' for v, k, x in nums)
    finds = "".join(f'<li><span class="{"up" if ok else "down"}" style="font-weight:700">{"✓" if ok else "✗"}</span> {e(text)}</li>'
                    for ok, text in sorted(_findings(result), key=lambda t: t[0]))
    todos = _todos(result, baseline, tags, f"evals/results/{result['run_id']}.json")
    todo_html = "".join(f"<li>☐ {t}</li>" for t in todos) or "<li>Nothing to do.</li>"
    problems = [c for c in result["cases"] if c["status"] != "PASS"]
    details = "".join(_detail(c, tags, open_=False) for c in result["cases"])
    hist = _history(history_rows or [], result["run_id"], baseline["run_id"] if baseline else None)
    tech = []
    for title, body in (("Planted-fact grid", _grid(result, baseline, tags)), ("Real data · table", _regression(result, tags)),
                        ("When things go wrong · checks", _robustness(result, tags)), ("Marcus · table", _marcus(result, tags))):
        if body:
            tech.append(f"<h3>{e(title)}</h3>{body}")
    sections = [
        f'<header class="top"><div><h1>Nexus eval · {e(when)}</h1><p class="sub">How well Ava (research) and Marcus (portfolio manager) did on frozen data for '
        f'{e(", ".join(sorted(p["snapshots"])))}</p></div><div class="chips">{"".join(chips)}</div></header>',
        f'<div class="tiles">{big}</div>',
        f'<section><div class="sec-head"><h2>What we learned</h2></div><div class="panel" style="padding:6px 18px">'
        f'<ul class="finds">{finds}</ul></div></section>',
        f'<section><div class="sec-head"><h2>Your to-do ({len(todos)})</h2><p>Code graded everything else. These need a person.</p></div>'
        f'<div class="panel" style="padding:6px 18px"><ul class="todo">{todo_html}</ul></div></section>',
        f'<section><div class="sec-head"><h2>All tests</h2><p>Each test in plain words. Groups with a problem are open. Click a test id for its runs and checks.</p></div>{_plain_tests(result, tags)}</section>',
        f'<details class="panel" id="offline"><summary class="empty" style="cursor:pointer"><b style="color:var(--ink)">Offline checks</b> · '
        f'{e((str(off["total"].get("PASS", 0)) + " of " + str(off["items"]) + " pass") if off else "not run")} <span class="small">· data and code, no model</span></summary>'
        f'<div style="padding:0 16px 16px">{_offline_section(result.get("offline"), preflight=True)}</div></details>',
        f'<details class="panel"><summary class="empty" style="cursor:pointer"><b style="color:var(--ink)">Run details</b> <span class="small">· versions, data, cost, command</span></summary>'
        f'{_meta(result, baseline)}</details>',
        f'<details class="panel"><summary class="empty" style="cursor:pointer"><b style="color:var(--ink)">Technical detail</b> <span class="small">· grids, every run and every check, for debugging</span></summary>'
        f'<div style="padding:0 16px 16px;display:grid;gap:14px">{"".join(tech)}<h3>Every test</h3><div class="panel">{details}</div></div></details>',
    ]
    if hist:
        sections.append(f'<details class="panel"><summary class="empty" style="cursor:pointer"><b style="color:var(--ink)">Run history</b></summary><div style="padding:0 16px 16px">{hist}</div></details>')
    return head + "\n".join(sections) + tail


def render(result: dict[str, Any], baseline: dict[str, Any] | None = None, history: list[dict[str, Any]] | None = None) -> str:
    kind = result.get("kind", "online")
    p = result["provenance"]
    tickers = sorted(p["snapshots"])
    hist = _history(history or [], result["run_id"], baseline["run_id"] if baseline else None)
    head = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>Nexus eval {e(result["run_id"])}</title>\n<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">\n'
            f"<style>\n{CSS}\n</style>\n</head>\n<body>\n<main>\n")
    tail = "\n</main>\n</body>\n</html>\n"

    if kind == "offline":
        off = result["offline"]["summary"]
        chips = [f'<span class="chip">run {e(result["run_id"])}</span>', '<span class="chip ok">OFFLINE · free, no model</span>']
        fails = off["total"].get("FAIL", 0)
        sections = [
            f'<header class="top"><div><h1>Nexus eval report · offline checks</h1><p class="sub">No model calls · {len(tickers)} snapshots: {e(", ".join(tickers))}</p></div>'
            f'<div class="chips">{"".join(chips)}</div></header>',
            _split(result),
            f'<section><div class="sec-head"><h2>What was run</h2></div><div class="panel">{_offline_meta(result)}</div></section>',
            f'<section id="offline"><div class="sec-head"><h2>Part 1 · Offline checks</h2><p>{off["total"].get("PASS", 0)} of {off["items"]} pass'
            + (f", {fails} fail" if fails else "") + f'.</p></div>{_offline_section(result["offline"], preflight=False)}</section>',
            '<section id="online"><div class="sec-head"><h2>Part 2 · Online evals</h2></div>'
            '<div class="panel empty">Not run. Online evals call Claude and cost money: python evals/run_evals.py --quick --yes</div></section>',
        ]
        if hist:
            sections.append(f'<section><div class="sec-head"><h2>Run history</h2><p>Offline and online runs, newest last.</p></div>{hist}</section>')
        return head + "\n".join(sections) + tail

    return _render_findings_first(result, baseline, history, head, tail)


def apply_reviews(result: dict[str, Any], verdicts: dict[str, str], today: str) -> list[str]:
    """Set the status of REVIEW cases to the person's verdict (PASS or FAIL). Returns the case ids changed."""
    from evals.run_evals import summarize

    by_id = {c["case_id"]: c for c in result.get("cases", [])}
    for cid, v in verdicts.items():
        if cid not in by_id:
            raise ValueError(f"{cid}: not in this run")
        if v not in ("PASS", "FAIL"):
            raise ValueError(f"{cid}: verdict must be PASS or FAIL, not {v}")
        c = by_id[cid]
        was = c.get("review", {}).get("was", c["status"])
        if was != "REVIEW":
            raise ValueError(f"{cid}: code graded it {was}; only REVIEW cases take a verdict")
        c["review"] = {"verdict": v, "was": was, "date": today}
        c["status"] = v
    result["summary"] = summarize(result["cases"])
    return list(verdicts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", nargs="?", help="results JSON to render")
    ap.add_argument("--baseline", help="results JSON to compare with (default: the accepted baseline)")
    ap.add_argument("--accept", metavar="RESULT", help="make this results JSON the baseline")
    ap.add_argument("--review", nargs="+", metavar="ARG", help="RESULT CASE=PASS|FAIL ...: record your verdict on REVIEW cases")
    args = ap.parse_args()
    if args.review:
        from datetime import date

        p, pairs = Path(args.review[0]), args.review[1:]
        try:
            verdicts = dict(a.split("=", 1) for a in pairs)
            result = load(p)
            changed = apply_reviews(result, {k.strip(): v.strip().upper() for k, v in verdicts.items()}, date.today().isoformat())
        except ValueError as exc:
            print(f"Nothing saved: {exc}")
            return 2
        p.write_text(json.dumps(result, indent=1))
        p.with_suffix(".html").write_text(render(result, load_baseline(None), history(p.parent)))
        print(f"Recorded {', '.join(f'{c}={verdicts[c]}' for c in changed)} in {p.name}; report re-rendered.")
        return 0
    if args.accept:
        p = Path(args.accept).resolve()
        if not p.exists() or p.parent != RESULTS_DIR.resolve():
            print(f"{args.accept}: not a file in {RESULTS_DIR.relative_to(ROOT)}")
            return 2
        BASELINE_FILE.write_text(p.name + "\n")
        print(f"Baseline is now {p.name}. Later runs report NEW FAIL / FIXED against it.")
        p.with_suffix(".html").write_text(render(load(p), load(p), history(RESULTS_DIR)))
        return 0
    if not args.result:
        ap.print_help()
        return 2
    result = load(args.result)
    out = Path(args.result).with_suffix(".html")
    out.write_text(render(result, load_baseline(args.baseline), history(Path(args.result).parent)))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
