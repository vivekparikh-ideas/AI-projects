"""Landing: the skill staircase, what Gap Finder does, and the "do this together" note."""
import streamlit as st

from ui import frame
from ui.components import coverage_note, show, staircase, together_note


def render(go) -> None:
    frame.header()
    show(staircase())
    show('<div class="gf-h1" style="margin-top:18px">Find the math skill behind tonight\'s homework.</div>'
         '<p class="gf-lede">Every skill stands on the steps before it. A quick check finds the missing step, '
         'with free lessons to fix it.</p>')
    show(f'<div style="display:flex;flex-direction:column;gap:10px;margin:16px 0 18px">{together_note()}{coverage_note()}</div>')
    st.button("Start", type="primary", width="stretch", on_click=go, args=("problem",), key="landing-start")
    show('<p class="gf-muted" style="text-align:center;margin-top:8px">Free · no account · nothing about your child is saved</p>')
    frame.footer(standards=False, lessons=False)
