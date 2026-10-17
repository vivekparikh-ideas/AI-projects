"""Step 2 (only when the match is uncertain): the parent picks one of two skills, shown with official text."""
import streamlit as st

from gapfinder.agent.resources import neo4j
from gapfinder.graph import queries as Q
from ui import frame
from ui.components import esc, show, tilly, truncate


def _grade(code: str) -> str:
    g = code.split(".")[0]
    return "Kindergarten" if g == "K" else f"Grade {g}"


def render(choices: list[dict], problem_text: str, state: str | None, on_pick, on_edit, on_start_over) -> None:
    frame.header(on_start_over)
    frame.step_bar(2)
    show(f'<div style="display:flex;gap:12px;align-items:flex-start;margin:8px 0 6px">{tilly(46, "curious", -8)}'
         '<div><div class="gf-h1" style="font-size:25px">Quick question: which skill is this?</div>'
         f'<p class="gf-muted" style="margin:0">“{esc(truncate(problem_text, 60))}” could be either. '
         'Pick the one closest to what your child is learning.</p></div></div>')

    by_code = {c["code"]: c for c in choices}
    picked = st.radio("Choose the skill", list(by_code), key="skill_pick", label_visibility="collapsed",
                      format_func=lambda c: f"{c} · {_grade(c)}",
                      captions=[truncate(c["text"], 130) for c in choices])
    with st.expander("Show full text"):
        for c in choices:
            show(f'<p style="font-size:14px"><span class="gf-code">{esc(c["code"])}</span> {esc(c["text"])}</p>')

    if state and picked:
        wording = Q.state_wording(neo4j(), state, picked)
        if wording:
            same = (wording.get("jaccard") or 0) >= 0.999
            text = (f"{esc(state)} uses this same wording" if same else
                    f"{esc(state)}'s version is {esc(wording['code'])}") + f" (crosswalk match {round((wording.get('jaccard') or 0) * 100)}%)."
            show(f'<div class="gf-note wording" style="margin:10px 0">{text}</div>')

    with st.container(key="confirm-actions"):
        st.button("That's the one", type="primary", width="stretch", on_click=on_pick, args=(picked,), key="confirm-pick")
        st.button("Neither of these? Edit the problem", type="tertiary", width="stretch", on_click=on_edit, key="confirm-edit")
    frame.footer(lessons=False)
