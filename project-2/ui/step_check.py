"""Step 3: the "check together" handover, then one question per screen. Right or wrong is never shown."""
import streamlit as st

from gapfinder.answers import RELATIONS, AnswerError, describe, parse_value
from ui import frame
from ui.components import GRAPE, TOMATO, esc, role_line, show, tile_bar, tilly, to_markdown_math

COMPARE_LABELS = {"<": "is less than", "=": "equals", ">": "is greater than"}


def render_together(n_questions: int, on_ready, on_start_over) -> None:
    frame.header(on_start_over)
    frame.step_bar(3, in_progress=True)
    show('<div class="gf-h1">Time to check together!</div><p class="gf-lede">Sit side by side. Here\'s who does what.</p>')
    show(f'<div style="display:flex;align-items:flex-end;gap:10px;margin:14px 0 4px">{tilly(62, "happy", -8)}'
         '<div class="gf-card" style="padding:12px 14px;border-radius:18px 18px 18px 4px;font-family:Fredoka,sans-serif;font-weight:500;font-size:17px">'
         f"Hi! I'm Tilly. Let's do {n_questions} quick questions. Just try your best!</div></div>"
         '<p class="gf-muted" style="margin:0 0 12px 72px;font-size:11.5px">Read Tilly\'s hello to your child</p>')
    card = ('<section style="padding:14px;border-radius:18px;background:{bg};border:2px solid {bd};display:flex;flex-direction:column;gap:6px">'
            '<div class="gf-h2" style="font-size:17px;margin:0">{title}</div><ul style="margin:0;padding-left:16px;font-size:12.5px;line-height:1.45">{items}</ul></section>')
    child = card.format(bg="#E3F5F2", bd="#1FA595", title="Your child", items="<li>Solves each question on paper</li>"
                        "<li>Says the answer out loud</li><li>Can say “I don't know”. That's useful too</li>")
    parent = card.format(bg="#EEF2FF", bd="#3550D6", title="You", items="<li>Read the question, or show the screen</li>"
                         "<li>Type exactly what they say</li><li>No hints, please. Wrong answers help find the gap</li>")
    show(f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px">{child}{parent}</div>')
    chips = "".join(f'<span class="gf-chip" style="background:#fff;border:1.5px solid #D9E0EC">{t}</span>'
                    for t in (f"{n_questions} questions", "About 5 minutes", "No scores shown"))
    show(f'<div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin:14px 0 18px">{chips}</div>')
    st.button("We're ready. Start!", type="primary", width="stretch", on_click=on_ready, key="ready")
    frame.footer(standards=False)


def _answer_note(value: str) -> tuple[bool, str]:
    try:
        forms = describe(parse_value(value))
    except AnswerError:
        return False, '<span style="color:#9E3322">We couldn\'t read that. Try 3/4, 0.75 or 1 1/2.</span>'
    extra = f" (that's {forms['mixed']})" if "mixed" in forms else ""
    return True, f'<span style="color:#1E6E47;font-weight:500">✓ We read this as {esc(forms["fraction"])}{esc(extra)}</span>'


def render_check(check: dict, on_answer, on_back, on_start_over) -> None:
    problems, i, rnd = check["problems"], check["i"], check["round"]
    p = problems[i]
    frame.header(on_start_over)

    if rnd > 1:
        show(f'<div style="display:flex;align-items:center;gap:12px;padding:14px 16px;border-radius:18px;background:#F4B740;'
             f'box-shadow:0 3px 0 #C98F17;margin-bottom:14px">{tilly(40, "cheer", -10)}<div><div style="font-family:Fredoka,sans-serif;'
             f'font-weight:700;font-size:19px">Almost there!</div><div style="font-size:13.5px">{len(problems)} more quick questions to be sure.</div></div></div>')
    eyebrow = "Round 2" if rnd > 1 else "Step 3 of 4 · The check"
    show(f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">'
         f'<span class="gf-eyebrow">{eyebrow}</span><span style="font-family:Fredoka,sans-serif;font-weight:600;font-size:15px">'
         f'Question {i + 1} of {len(problems)}</span></div>'
         + tile_bar(i, len(problems), GRAPE if rnd > 1 else TOMATO, label=f"{i} of {len(problems)} questions done"))

    with st.container(key="problem-card"):
        show(role_line())
        st.markdown(to_markdown_math(p["text"]))

    key = f"ans_{p['id']}"
    if key not in st.session_state and check["answers"].get(p["id"]):  # restore after "Back"
        st.session_state[key] = check["answers"][p["id"]]
    ready = False
    if p["kind"] == "comparison":
        st.markdown("**Your child's answer**")
        with st.container(horizontal=True, key="compare"):
            for sym, label in COMPARE_LABELS.items():
                if st.button(sym, key=f"{key}_{label}", help=label, width="stretch",
                             type="primary" if st.session_state.get(key) == sym else "secondary"):
                    st.session_state[key] = sym
                    st.rerun()
        if st.session_state.get(key):
            show(f'<p class="gf-muted">Answer: {esc(st.session_state[key])} ({COMPARE_LABELS[st.session_state[key]]})</p>')
        ready = st.session_state.get(key) in RELATIONS
    else:
        with st.container(key="answer-box"):
            st.text_input("Your child's answer", key=key, placeholder="e.g. 3/4")
        value = (st.session_state.get(key) or "").strip()
        if value:
            ready, note = _answer_note(value)
            show(f'<p style="font-size:13.5px;margin:4px 0 0">{note}</p>')
        show('<p class="gf-muted" style="margin:4px 0 0">Fractions like 3/4, decimals like 0.75 and mixed numbers like 1 1/2 all work.</p>')

    show('<p class="gf-muted" style="text-align:center;margin:18px 0 8px">No right or wrong is shown. Every answer helps, even “I don\'t know”.</p>')
    with st.container(horizontal=True, key="check-actions"):
        st.button("They don't know", width="stretch", on_click=on_answer, args=(p["id"], None), key=f"{key}_idk")
        st.button("Next", type="primary", width="stretch", disabled=not ready, key=f"{key}_next",
                  on_click=on_answer, args=(p["id"], (st.session_state.get(key) or "").strip()))
    if i > 0:
        st.button(f"Back to question {i}", type="tertiary", width="stretch", on_click=on_back, key=f"{key}_back")
    frame.footer(standards=False)
