"""Gap Finder: find the math skill behind tonight's homework.

Run with:  uv run streamlit run app.py
"""
import streamlit as st
from langgraph.types import Command

from gapfinder.agent import sessions
from gapfinder.agent.followup import ask_why
from gapfinder.agent.graph import agent
from gapfinder.agent.resources import neo4j
from gapfinder.graph import queries as Q
from gapfinder.vectors import retrieve
from ui import frame, landing, progress, step_check, step_confirm, step_problem, step_result
from ui.components import show

ss = st.session_state


@st.cache_resource(show_spinner="Getting ready…")
def warm_up() -> list[str]:
    """Open every connection once per process, so the first parent doesn't wait (decision #18)."""
    sessions.purge()
    agent()
    neo4j().verify_connectivity()
    index, embedder = retrieve._clients()
    index.describe_index_stats()
    return Q.jurisdictions(neo4j())


def config() -> dict:
    return {"configurable": {"thread_id": ss.thread}}


def values() -> dict:
    return agent().get_state(config()).values


# ---------- navigation ----------

def go(screen: str) -> None:
    ss.screen = screen


def start_over() -> None:
    for key in list(ss.keys()):
        del ss[key]
    ss.screen = "landing"


def check_another() -> None:
    saved = ss.get("saved_inputs", {})
    start_over()
    ss.saved_inputs = {k: saved[k] for k in ("state_choice", "grade") if saved.get(k)}
    ss.screen = "problem"


def submit_problem(inputs: dict) -> None:
    ss.thread = sessions.new_thread()
    ss.pending = ("find", inputs)


def pick_skill(code: str) -> None:
    ss.pending = ("confirm", code)


def answer(problem_id: str, value: str | None) -> None:
    check = ss.check
    check["answers"][problem_id] = value or None
    if check["i"] < len(check["problems"]) - 1:
        check["i"] += 1
    else:
        ss.pending = ("answers", check["answers"])


def back() -> None:
    ss.check["i"] = max(0, ss.check["i"] - 1)


def ask(question: str) -> None:
    ask_why(ss.thread, question)


# ---------- agent requests (run behind the waiting screen) ----------

def handle_pending() -> None:
    kind, payload = ss.pop("pending")
    frame.header()
    try:
        if kind == "find":
            pause, final = progress.run(payload, ss.thread, progress.FIND)
        elif kind == "confirm":
            pause, final = progress.run(Command(resume=payload), ss.thread, progress.CONFIRMED)
        else:
            pause, final = progress.run(Command(resume=payload), ss.thread, progress.ANSWERS, title="Finding the gap…")
    except Exception:  # noqa: BLE001 - the parent sees a friendly message, never a stack trace
        ss.screen, ss.error = "error", True
        st.rerun()
        return

    result = final.get("result") or {}
    if pause is None:
        if result.get("not_math"):
            ss.screen = "problem"
            ss.problem_error = "This doesn't look like a math problem. Try copying it exactly as it appears on the worksheet."
        else:
            ss.screen = "notyet" if result.get("cannot_check") else "result"
    elif pause["type"] == "confirm_skill":
        ss.choices, ss.screen = pause["choices"], "confirm"
    else:
        ss.check = {"round": pause["round"], "problems": pause["problems"], "i": 0, "answers": {}}
        ss.screen = "together" if pause["round"] == 1 else "check"
    st.rerun()


def render_error() -> None:
    frame.header(start_over)
    show('<div class="gf-h1" style="margin-top:20px">Something went wrong on our side.</div>'
         "<p class=\"gf-lede\">Your answers weren't saved anywhere. Please try again.</p>")
    st.button("Try again", type="primary", width="stretch", on_click=check_another, key="error-retry")


def main() -> None:
    st.set_page_config(page_title="Gap Finder", page_icon=":material/stairs:", layout="centered",
                       initial_sidebar_state="collapsed")
    frame.inject_styles()
    states = warm_up()
    ss.setdefault("screen", "landing")

    if ss.get("pending"):
        handle_pending()
        return

    screen = ss.screen
    if screen == "landing":
        landing.render(go)
    elif screen == "problem":
        step_problem.render(states, submit_problem, start_over)
    elif screen == "confirm":
        v = values()
        step_confirm.render(ss.choices, v.get("problem_text", ""), v.get("state_code"), pick_skill, lambda: go("problem"), start_over)
    elif screen == "together":
        step_check.render_together(len(ss.check["problems"]), lambda: go("check"), start_over)
    elif screen == "check":
        step_check.render_check(ss.check, answer, back, start_over)
    elif screen == "result":
        step_result.render(values(), ask, check_another, start_over)
    elif screen == "notyet":
        step_result.render_not_yet(values(), check_another, start_over)
    else:
        render_error()


if __name__ == "__main__":
    main()
