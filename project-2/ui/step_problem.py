"""Step 1: state, grade and the homework problem."""
import re

import streamlit as st

from ui import frame
from ui.components import esc, show

COMMON_CORE = "Common Core (not sure)"
GRADES = ["K", "1", "2", "3", "4", "5", "6", "7", "8"]
EXAMPLES = {"2/3 + 1/4 = ?": "5", "Which is greater, 2/3 or 3/5?": "4", "3/4 ÷ 1/8 = ?": "6"}


def _use_example() -> None:
    picked = st.session_state.get("example")
    if picked:
        st.session_state.problem_text = picked
        st.session_state.grade = EXAMPLES[picked]


def render(states: list[str], on_submit, on_start_over) -> None:
    ss = st.session_state
    # Streamlit drops widget values once a widget leaves the screen; restore them from the saved copy.
    for key, value in ss.get("saved_inputs", {}).items():
        if key not in ss and value:
            ss[key] = value
    frame.header(on_start_over)
    frame.step_bar(1)
    show('<div class="gf-h1">What\'s tonight\'s tricky problem?</div>')

    with st.container(key="problem-form"):
        st.selectbox("Your state", [COMMON_CORE] + states, key="state_choice")
        st.segmented_control("Grade", GRADES, key="grade")
        st.text_area("The problem, as it appears on the worksheet", key="problem_text", height=110,
                     placeholder="e.g. 3/4 ÷ 1/8 = ?", help="Type fractions with a slash, like 3/4.")
        st.pills("Or try an example", list(EXAMPLES), key="example", on_change=_use_example)

    if ss.get("problem_error"):
        show(f'<div class="gf-note coverage" role="alert"><span>{esc(ss.problem_error)}</span></div>')
    show('<p class="gf-muted" style="margin:10px 2px 14px">Right now Gap Finder works for fraction homework in grades 3–6. More topics coming.</p>')

    if st.button("Find the gap →", type="primary", width="stretch", key="find"):
        text = (ss.get("problem_text") or "").strip()
        if not ss.get("grade"):
            ss.problem_error = "Pick your child's grade."
        elif not text:
            ss.problem_error = "Type the problem your child is stuck on."
        elif not re.search(r"\d", text):
            ss.problem_error = "This doesn't look like a math problem. Try copying it exactly as it appears on the worksheet."
        else:
            ss.problem_error = None
            ss.saved_inputs = {"state_choice": ss.state_choice, "grade": ss.grade, "problem_text": text}
            state = None if ss.state_choice == COMMON_CORE else ss.state_choice
            on_submit({"grade": ss.grade, "state_code": state, "problem_text": text})
        st.rerun()
    frame.footer(lessons=False)
