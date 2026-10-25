"""Eval harness for Ava and Marcus on live data (D-012).

Each ticker runs Research → PM with no fund (advice path; nothing is traded), `--reruns` times.
Code graders, per run:
  completed   the dossier passed schema + grounding (every number traced to a tool output)
  repaired    it needed the one allowed repair
  within_cap  follow-up tool calls ≤ 8
  decided     Marcus returned BUY / SELL / HOLD advice (not a forced HOLD from a failure)
  prices_ok   Marcus's prices passed the code sanity check
Per ticker, across reruns:
  stable_action      the same action every time
  conviction_spread  max − min conviction (target ≤ 1.0)

    python evals/run_evals.py --tickers NVDA,KO --reruns 1          # smoke test
    python evals/run_evals.py --yes                                 # full golden set (prints the estimate first)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nexus import data, llm, policies  # noqa: E402
from nexus.graph import build_graph, initial_state  # noqa: E402
from nexus.state import MAX_AGENT_TOOL_CALLS  # noqa: E402

EST_COST_PER_RUN = 0.12  # USD, observed on early live runs (≈17k research + 2k PM tokens)


def run_once(ticker: str) -> dict[str, Any]:
    state = initial_state(ticker, fund=None)
    final: dict[str, Any] = {}
    custom: list[dict[str, Any]] = []
    before = llm.cost_usd(llm.SESSION)
    try:
        for mode, chunk in build_graph().stream(state, config={"configurable": {"speed": 0, "approval": "auto"}, "recursion_limit": 40}, stream_mode=["custom", "values"]):
            if mode == "values":
                final = chunk
            else:
                custom.append(chunk)
    except Exception as exc:  # a crash is a result, not a harness failure
        return {"ticker": ticker, "error": f"{type(exc).__name__}: {exc}", "cost": llm.cost_usd(llm.SESSION) - before}
    records = final.get("handoff_log", [])
    research = [r for r in records if r.agent_id == "research_analyst"]
    pm = [r for r in records if r.agent_id == "portfolio_manager"]
    failed_submits = [c for c in custom if c.get("type") == "micro_action" and c["event"]["action_id"] == "submit_dossier" and c["event"]["status"] == "FAILED"]
    dossier = final.get("dossier")
    rec, intent = final.get("recommendation"), final.get("intent")
    action = rec.action if rec else intent.action if intent else None
    rationale = (intent.rationale if intent else "") or ""
    return {
        "ticker": ticker,
        "completed": bool(research) and research[-1].status == "COMPLETED",
        "repaired": bool(failed_submits),
        "within_cap": len(final.get("agent_trace", [])) <= MAX_AGENT_TOOL_CALLS * 2,  # two research rounds at most
        "decided": action is not None and not rationale.startswith(("Research could not", "Stopped", "No decision")),
        "prices_ok": "sanity check" not in rationale,
        "action": action,
        "weight_pct": rec.target_weight_pct if rec else None,
        "conviction": dossier.conviction_score if dossier else None,
        "base_score": dossier.scorecard.base_score if dossier else None,
        "follow_ups": [s.tool for s in final.get("agent_trace", [])],
        "research_rounds": final.get("research_rounds"),
        "error_note": research[-1].handoff.why_rationale if research and research[-1].status == "FAILED" else "",
        "tokens": sum(r.tokens or 0 for r in research + pm),
        "cost": round(llm.cost_usd(llm.SESSION) - before, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated subset; default: evals/golden.yaml")
    ap.add_argument("--reruns", type=int, default=3)
    ap.add_argument("--yes", action="store_true", help="required for runs estimated above $2")
    args = ap.parse_args()
    console = Console()

    tickers = args.tickers.split(",") if args.tickers else yaml.safe_load((ROOT / "evals/golden.yaml").read_text())["tickers"]
    runs = len(tickers) * args.reruns
    estimate = runs * EST_COST_PER_RUN
    console.print(f"{len(tickers)} tickers × {args.reruns} reruns = {runs} live runs, estimated ${estimate:.2f}")
    if estimate > 2 and not args.yes:
        console.print("[yellow]Pass --yes to run it.[/yellow]")
        return 2

    load_dotenv(ROOT / ".env")
    data.use("live")
    policies.set_mode("claude")
    results = []
    for t in tickers:
        for i in range(args.reruns):
            r = run_once(t.strip().upper())
            r["rerun"] = i + 1
            results.append(r)
            status = "ERROR " + r["error"] if "error" in r else f"{r['action']} conv {r['conviction']} · {len(r['follow_ups'])} tools · ${r['cost']:.3f}"
            console.print(f"  {t:6s} #{i + 1}  {status}")

    table = Table(title="Eval results")
    for col in ("ticker", "completed", "decided", "prices_ok", "stable", "conviction", "spread", "actions"):
        table.add_column(col)
    summary = {"completed": 0, "decided": 0, "prices_ok": 0, "within_cap": 0, "stable": 0, "spread_ok": 0, "runs": len(results), "tickers": len(tickers)}
    per_ticker = {}
    for t in tickers:
        rs = [r for r in results if r["ticker"] == t.strip().upper()]
        ok = [r for r in rs if "error" not in r]
        convs = [r["conviction"] for r in ok if r["conviction"] is not None]
        actions = [r["action"] for r in ok]
        stable = len(set(actions)) == 1 and len(actions) == len(rs)
        spread = round(max(convs) - min(convs), 1) if len(convs) > 1 else 0.0
        for key in ("completed", "decided", "prices_ok", "within_cap"):
            summary[key] += sum(1 for r in ok if r[key])
        summary["stable"] += stable
        summary["spread_ok"] += spread <= 1.0
        per_ticker[t] = {"stable_action": stable, "conviction_spread": spread}
        table.add_row(t, f"{sum(r['completed'] for r in ok)}/{len(rs)}", f"{sum(r['decided'] for r in ok)}/{len(rs)}",
                      f"{sum(r['prices_ok'] for r in ok)}/{len(rs)}", "yes" if stable else "NO",
                      ", ".join(f"{c:.1f}" for c in convs), f"{spread:.1f}", ", ".join(str(a) for a in actions))
    console.print(table)
    spent = llm.cost_usd(llm.SESSION)
    n = summary["runs"]
    console.print(
        f"completed {summary['completed']}/{n} · decided {summary['decided']}/{n} · prices ok {summary['prices_ok']}/{n} · "
        f"within cap {summary['within_cap']}/{n} · stable actions {summary['stable']}/{summary['tickers']} · "
        f"conviction spread ≤ 1.0 {summary['spread_ok']}/{summary['tickers']} · spent ${spent:.2f}"
    )
    out = ROOT / "evals/results" / f"{datetime.now():%Y-%m-%d-%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "per_ticker": per_ticker, "runs": results, "spent_usd": round(spent, 2),
                               "model": llm.MODEL, "prompts": [policies.RESEARCH_PROMPT_VERSION, policies.PM_PROMPT_VERSION]}, indent=2, default=str))
    console.print(f"Saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
