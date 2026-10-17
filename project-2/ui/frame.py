"""The frame every screen shares: styles, header with Start over, the step bar and the footer."""
from pathlib import Path

import streamlit as st

from gapfinder.config import CCSS_NOTICE
from ui.components import TILE_COLORS, logo, show

STEP_NAMES = {1: "The problem", 2: "Confirm the skill", 3: "The check", 4: "The result"}
IM_LINE = "Lessons and check questions: Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0."


def inject_styles() -> None:
    css = (Path(__file__).with_name("styles.css")).read_text(encoding="utf-8")
    show(f"<style>{css}</style>")


def header(on_start_over=None) -> None:
    with st.container(horizontal=True, vertical_alignment="center", key="gf-header"):
        show(logo())
        st.space("stretch")
        if on_start_over:
            st.button("Start over", type="tertiary", on_click=on_start_over, key="start-over")
        else:
            show('<span class="gf-muted" style="font-weight:500">Free &amp; open source</span>')


def step_bar(step: int, in_progress: bool = False) -> None:
    tiles = []
    for i in range(4):
        if i < step - 1 or (i == step - 1 and not in_progress):
            style = f"background:{TILE_COLORS[i]}"
        elif i == step - 1:
            style = f"border:2px dashed {TILE_COLORS[i]};box-sizing:border-box;background:#fff"
        else:
            style = "background:#fff;border:1.5px solid #D9E0EC;box-sizing:border-box"
        tiles.append(f'<div style="flex:1;height:10px;border-radius:4px;{style}"></div>')
    show(f'<div aria-label="Step {step} of 4" style="display:flex;flex-direction:column;gap:6px;margin-bottom:6px">'
         f'<span class="gf-eyebrow">Step {step} of 4 · {STEP_NAMES[step]}</span>'
         f'<div aria-hidden="true" style="display:flex;gap:4px">{"".join(tiles)}</div></div>')


def footer(standards: bool = True, lessons: bool = True) -> None:
    lines = ['<span style="font-weight:600;color:#1C2541">Nothing about your child is saved.</span>']
    if standards:
        lines.append(f"<span>Standards: {CCSS_NOTICE}</span>")
    if lessons:
        lines.append(f"<span>{IM_LINE} Answer keys by Gap Finder, reviewed by a teacher.</span>")
    show('<footer style="margin-top:28px;padding-top:14px;border-top:1.5px solid #D9E0EC;display:flex;flex-direction:column;'
         f'gap:6px;font-size:11.5px;line-height:1.5;color:#59627A">{"".join(lines)}</footer>')
