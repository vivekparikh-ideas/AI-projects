"""Run the agent end to end with a simulated child, timing each request.

The simulated child answers correctly for skills listed in --knows and says "didn't know" otherwise.
It reads answer keys from the server-side state, which the real screen never sees.

Usage:
  uv run python scripts/demo_agent.py --grade 6 --state Texas --problem "3/4 ÷ 1/8 = ?" --knows 4.NF.B.4
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from langgraph.types import Command  # noqa: E402

from gapfinder.agent.followup import ask_why  # noqa: E402
from gapfinder.agent.graph import agent  # noqa: E402


def pause_of(out: dict):
    interrupts = out.get("__interrupt__") or []
    return interrupts[0].value if interrupts else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", default="6")
    ap.add_argument("--state", default=None)
    ap.add_argument("--problem", default="3/4 ÷ 1/8 = ?")
    ap.add_argument("--knows", nargs="*", default=["4.NF.B.4"], help="skill codes the simulated child has mastered")
    ap.add_argument("--ask", default="Why does this skill come before dividing fractions?")
    args = ap.parse_args()

    graph = agent()
    config = {"configurable": {"thread_id": f"demo-{uuid.uuid4().hex[:8]}"}}
    request = 1

    t = time.perf_counter()
    out = graph.invoke({"grade": args.grade, "state_code": args.state, "problem_text": args.problem}, config)
    print(f"\nRequest {request} (find the gap): {time.perf_counter() - t:.1f} s")
    s = graph.get_state(config).values
    print(f"  skill: {s.get('skill_description')}")
    print(f"  matched: {s.get('target_code')} (confidence {s.get('confidence')}) | candidates: {[c['code'] for c in s.get('candidates', [])]}")
    if s.get("state_wording"):
        print(f"  {args.state} wording: {s['state_wording']['code']} (crosswalk {s['state_wording']['jaccard']:.2f})")

    while (pause := pause_of(out)) is not None:
        request += 1
        if pause["type"] == "confirm_skill":
            print(f"  -> pause: confirm skill, choices {[c['code'] for c in pause['choices']]}; choosing the first")
            resume = pause["choices"][0]["code"]
        else:
            state = graph.get_state(config).values
            keys = {c["id"]: c for c in state["checks"]}
            print(f"  -> pause: check round {pause['round']} with {len(pause['problems'])} problems")
            resume = {}
            for p in pause["problems"]:
                c = keys[p["id"]]
                knows = any(c["skill_code"] == k or c["skill_code"].startswith(k + ".") for k in args.knows)
                resume[p["id"]] = c["answer_key"] if knows else None
                print(f"     [{c['skill_code']:<9}] {p['text'][:70]!r:<74} -> {resume[p['id']] or 'didn’t know'}")
        t = time.perf_counter()
        out = graph.invoke(Command(resume=resume), config)
        print(f"\nRequest {request}: {time.perf_counter() - t:.1f} s")

    s = graph.get_state(config).values
    print("  verdicts:", s.get("verdicts"))
    print("  gap:", s.get("gap"))
    print("  result:", json.dumps(s.get("result"), ensure_ascii=False, indent=2))
    print("  lessons:", [(l["id"], l["title"]) for l in s.get("lessons", [])])
    print("  rewrites:", s.get("retry_count"))

    if args.ask and s.get("result") and not s["result"].get("not_math"):
        t = time.perf_counter()
        turn = ask_why(config["configurable"]["thread_id"], args.ask)
        print(f"\nRequest {request + 1} (Ask why): {time.perf_counter() - t:.1f} s")
        print("  Q:", args.ask)
        print("  A:", turn["answer"], "| grounded:", turn["grounded"], "| lessons:", turn["lesson_ids"])


if __name__ == "__main__":
    main()
