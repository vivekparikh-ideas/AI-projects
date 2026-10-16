"""Click through the real app with Streamlit's AppTest harness (live agent, Neo4j, Pinecone, OpenAI).

Simulated child: answers correctly for skills in KNOWS, says "didn't know" otherwise.

Usage: uv run python scripts/smoke_app.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest  # noqa: E402

from gapfinder.agent.graph import agent  # noqa: E402

TIMEOUT = 120


def fail_if_error(at: AppTest, where: str) -> None:
    if at.exception:
        raise SystemExit(f"Exception on {where}: {at.exception[0].message}\n{at.exception[0].stack_trace}")
    if at.session_state["screen"] == "error":
        raise SystemExit(f"Friendly error screen shown on {where}")


def text_of(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def find_gap(problem: str, grade: str, state: str, knows: list[str]) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.run()
    fail_if_error(at, "landing")
    assert "Find the math skill behind tonight" in text_of(at), "landing headline missing"
    at.button(key="landing-start").click().run()
    assert at.session_state["screen"] == "problem"

    at.selectbox(key="state_choice").set_value(state)
    at.session_state["grade"] = grade
    at.text_area(key="problem_text").input(problem)
    t = time.perf_counter()
    at.button(key="find").click().run()
    fail_if_error(at, "find")
    print(f"  find the gap -> screen '{at.session_state['screen']}' in {time.perf_counter() - t:.1f} s")

    if at.session_state["screen"] == "confirm":
        at.button(key="confirm-pick").click().run()
        fail_if_error(at, "confirm")
        print(f"  confirmed -> screen '{at.session_state['screen']}'")
    if at.session_state["screen"] == "notyet":
        return at

    assert at.session_state["screen"] == "together", at.session_state["screen"]
    assert "Time to check together" in text_of(at)
    at.button(key="ready").click().run()

    config = {"configurable": {"thread_id": at.session_state["thread"]}}
    while at.session_state["screen"] == "check":
        check = at.session_state["check"]
        p = check["problems"][check["i"]]
        server = {c["id"]: c for c in agent().get_state(config).values["checks"]}[p["id"]]
        knows_it = any(server["skill_code"] == k or server["skill_code"].startswith(k + ".") for k in knows)
        key = f"ans_{p['id']}"
        if not knows_it:
            at.button(key=f"{key}_idk").click().run()
        elif p["kind"] == "comparison":
            label = {"<": "is less than", "=": "equals", ">": "is greater than"}[server["answer_key"]]
            at.button(key=f"{key}_{label}").click().run()
            at.button(key=f"{key}_next").click().run()
        else:
            at.text_input(key=key).input(server["answer_key"]).run()
            assert "We read this as" in text_of(at), "answer parse note missing"
            at.button(key=f"{key}_next").click().run()
        fail_if_error(at, f"question {check['i'] + 1} (round {check['round']})")
    return at


def main() -> None:
    print("Case 1: grade 6, Texas, 3/4 ÷ 1/8 (child knows 4.NF.B.4 and 3.NF.A.1)")
    at = find_gap("3/4 ÷ 1/8 = ?", "6", "Texas", ["4.NF.B.4", "3.NF.A.1"])
    assert at.session_state["screen"] == "result", at.session_state["screen"]
    page = text_of(at)
    for expected in ("We found it!", "Free lessons to practice", "Ask why", "Nothing about your child is saved"):
        assert expected in page, f"result screen missing: {expected}"
    v = agent().get_state({"configurable": {"thread_id": at.session_state["thread"]}}).values
    print(f"  result: gap {v['gap']} | headline: {v['result'].get('headline')}")

    t = time.perf_counter()
    at.chat_input[0].set_value("How do I explain it?").run()
    fail_if_error(at, "ask why")
    v = agent().get_state({"configurable": {"thread_id": at.session_state["thread"]}}).values
    print(f"  ask why answered in {time.perf_counter() - t:.1f} s, grounded={v['chat'][-1]['grounded']}")

    at.button(key="another").click().run()
    assert at.session_state["screen"] == "problem" and at.selectbox(key="state_choice").value == "Texas", "check another lost the state"
    print("  'Check another problem' kept the state and grade")

    print("\nCase 2: grade 4, California, 3,452 × 6 (outside coverage)")
    at = find_gap("3,452 × 6 = ?", "4", "California", [])
    assert at.session_state["screen"] == "notyet", at.session_state["screen"]
    assert "We can't check this skill yet" in text_of(at)
    print("  -> 'can't check this skill yet' screen shown")

    print("\nCase 3: not math")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.run()
    at.button(key="landing-start").click().run()
    at.session_state["grade"] = "5"
    at.text_area(key="problem_text").input("What is photosynthesis?")
    at.button(key="find").click().run()
    assert at.session_state["screen"] == "problem" and "look like a math problem" in text_of(at)
    print("  -> stays on step 1 with a friendly message")
    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
