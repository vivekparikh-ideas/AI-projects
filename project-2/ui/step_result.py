"""Step 4: the result, "What we saw", lessons and Ask why. Also the "can't check this skill yet" screen."""
import streamlit as st

from ui import frame
from ui.components import BLUE, GRAPE, SUN, TOMATO, esc, show, tilly, truncate

PILL = {"high": ("high", "High confidence"), "medium": ("medium", "Medium confidence"), "low": ("low", "Low confidence")}
SUGGESTIONS = ["Why this skill?", "How do I explain it?", "What should we practice tonight?"]
OPEN_SVG = ('<svg role="img" aria-label="Opens in a new tab" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3550D6" '
            'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="flex:none"><path d="M14 4h6v6"></path>'
            '<line x1="20" y1="4" x2="11" y2="13"></line><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"></path></svg>')


def _grade(code: str) -> str:
    g = (code or "?").split(".")[0]
    return "Kindergarten" if g == "K" else f"Grade {g}"


def _lesson_cards(lessons: list[dict]) -> str:
    cards = []
    for n, l in enumerate(lessons):
        color = [SUN, TOMATO, GRAPE][n % 3]
        fg = "#1C2541" if color == SUN else "#fff"
        cards.append(
            f'<a href="{esc(l["url"])}" target="_blank" rel="noopener" style="display:flex;gap:14px;align-items:center;padding:14px;'
            'background:#fff;border-radius:18px;box-shadow:0 3px 0 #D9E0EC;text-decoration:none;color:#1C2541">'
            f'<span aria-hidden="true" style="flex:none;width:46px;height:46px;border-radius:12px;background:{color};color:{fg};display:flex;'
            f'align-items:center;justify-content:center;font-family:Fredoka,sans-serif;font-weight:700;font-size:18px">{esc(l["lesson"])}</span>'
            f'<span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px"><span style="font-weight:600;font-size:15px">{esc(l["title"])}</span>'
            f'<span class="gf-muted" style="font-size:12.5px">Grade {esc(l["grade"])} · Unit {esc(l["unit"])} · Lesson {esc(l["lesson"])}</span></span>'
            f'{OPEN_SVG}</a>')
    return '<div style="display:flex;flex-direction:column;gap:12px">' + "".join(cards) + "</div>"


def _what_we_saw(values: dict) -> str:
    rows = []
    gap_code = (values.get("gap") or {}).get("code")
    for s in values.get("skills", []):
        marks = [r["correct"] for r in values.get("results", []) if r["skill_code"] == s["code"]]
        if not marks:
            continue
        tiles = "".join(
            f'<span style="width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:700;'
            + ('background:#E2F4EA;color:#1E6E47">✓' if ok else 'background:#FBE3DE;color:#B23A26">✗') + "</span>" for ok in marks)
        is_gap = s["code"] == gap_code and (values.get("gap") or {}).get("kind") != "none"
        role = "homework skill" if s.get("role") == "target" else "earlier skill"
        tag = " · likely gap" if is_gap else ""
        rows.append(
            f'<li style="display:flex;gap:12px;align-items:center;{"padding:8px;margin:-8px;border-radius:12px;background:#FFF4DA;" if is_gap else ""}">'
            f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px"><span style="font-size:12px;color:#59627A;'
            f'{"font-weight:600" if is_gap else ""}"><span style="font-family:JetBrains Mono,monospace">{esc(s["code"])}</span> · {role}{tag}</span>'
            f'<span style="font-size:13.5px">{esc(truncate(s.get("text"), 70))}</span></div>'
            f'<span style="flex:none;display:flex;gap:4px" aria-label="{sum(marks)} of {len(marks)} right">{tiles}</span></li>')
    return f'<ul style="list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:14px">{"".join(rows)}</ul>'


def render(values: dict, ask, on_another, on_start_over) -> None:
    result, gap = values.get("result") or {}, values.get("gap") or {}
    frame.header(on_start_over)
    frame.step_bar(4)

    if result.get("abstained"):
        title, mood = "Here's what we saw", "flat"
    elif gap.get("kind") == "none":
        title, mood = "Nice work!", "cheer"
    elif gap.get("kind") == "unclear":
        title, mood = "Here's our best guess", "curious"
    else:
        title, mood = "We found it!", "cheer"
    show(f'<div style="display:flex;align-items:center;gap:14px;margin:12px 0 14px">{tilly(64, mood, -8)}'
         f'<div class="gf-h1" style="margin:0">{title}</div></div>')

    pill_cls, pill_text = PILL.get(gap.get("confidence"), ("low", "Low confidence"))
    label = {"gap": "Likely gap", "unclear": "Least certain skill", "none": "Homework skill"}.get(gap.get("kind"), "Result")
    pill = "" if result.get("abstained") else f'<span class="gf-pill {pill_cls}">{pill_text}</span>'
    skill = (f'<div style="padding:12px;border-radius:14px;background:#F3F5FA;display:flex;flex-direction:column;gap:4px">'
             f'<span><span class="gf-code">{esc(gap.get("code"))} · {_grade(gap.get("code"))}</span></span>'
             f'<span style="font-size:13px;line-height:1.45">{esc(values.get("gap_text"))}</span></div>') if gap.get("code") and not result.get("abstained") else ""
    show(f'<section class="gf-card"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
         f'<span class="gf-eyebrow">{label}</span>{pill}</div>'
         f'<div class="gf-h2" style="font-size:24px;line-height:1.2;margin:0">{esc(result.get("headline"))}</div>'
         f'<p class="gf-lede">{esc(result.get("why"))}</p>{skill}</section>')

    with st.expander("What we saw", expanded=True):
        show(_what_we_saw(values))

    by_id = {l["id"]: l for l in values.get("lessons", [])}
    lessons = [by_id[i] for i in result.get("lesson_ids", []) if i in by_id] or list(by_id.values())
    if lessons:
        show('<div class="gf-h2" style="margin-top:18px">Free lessons to practice</div>')
        show(_lesson_cards(lessons))
        show(f'<p class="gf-muted" style="font-size:11.5px;margin-top:8px">{frame.IM_LINE}</p>')

    show('<div class="gf-h2" style="margin-top:18px">Ask why</div>')
    picked = st.pills("Suggested questions", SUGGESTIONS, key="suggestion", label_visibility="collapsed")
    for turn in values.get("chat", []):
        with st.chat_message("user"):
            st.markdown(turn["question"])
        with st.chat_message("assistant"):
            st.markdown(turn["answer"])
            cited = [by_id[i] for i in turn.get("lesson_ids", []) if i in by_id]
            for l in cited:
                st.markdown(f"From: [{l['title']}]({l['url']})")
    question = st.chat_input("Ask a question about this result")
    if picked and picked != st.session_state.get("last_suggestion"):
        st.session_state.last_suggestion = picked
        question = picked
    if question:
        with st.spinner("Tilly is looking that up…"):
            ask(question)
        st.rerun()

    with st.container(key="result-actions"):
        st.button("Check another problem", type="primary", width="stretch", on_click=on_another, key="another")
        st.button("Start over", width="stretch", on_click=on_start_over, key="result-start-over")
    frame.footer()


def render_not_yet(values: dict, on_another, on_start_over) -> None:
    frame.header(on_start_over)
    show(f'<div style="display:flex;flex-direction:column;align-items:center;gap:8px;margin:18px 0 10px">{tilly(84, "flat", 5)}'
         f'<div style="display:flex;gap:5px;width:200px"><div style="flex:1;height:14px;border-radius:4px;background:{SUN}"></div>'
         '<div style="flex:1;height:14px;border-radius:4px;border:2px dashed #A6B0C4;box-sizing:border-box"></div>'
         '<div style="flex:1;height:14px;border-radius:4px;border:2px dashed #A6B0C4;box-sizing:border-box"></div></div></div>'
         '<div class="gf-h1" style="text-align:center">We can\'t check this skill yet</div>'
         '<p class="gf-lede" style="text-align:center">Right now Gap Finder has teacher-checked questions for fraction homework '
         "in grades 3–6. We're adding more topics.</p>")
    code = values.get("target_code")
    show(f'<section class="gf-card" style="margin-top:16px"><span class="gf-eyebrow">Your problem</span>'
         f'<span style="font-family:Fredoka,sans-serif;font-weight:500;font-size:22px">{esc(values.get("problem_text"))}</span>'
         '<span class="gf-muted">We matched it to this skill:</span>'
         f'<span><span class="gf-code">{esc(code)} · {_grade(code)}</span></span>'
         f'<span style="font-size:13.5px;line-height:1.45">{esc(truncate(values.get("target_text"), 220))}</span></section>')
    if values.get("lessons"):
        show('<div class="gf-h2" style="margin-top:18px">Lessons for this skill</div>')
        show(_lesson_cards(values["lessons"]))
        show(f'<p class="gf-muted" style="font-size:11.5px;margin-top:8px">{frame.IM_LINE}</p>')
    with st.container(key="notyet-actions"):
        st.space("small")
        st.button("Try a fraction problem", type="primary", width="stretch", on_click=on_another, key="notyet-another")
        st.button("Start over", width="stretch", on_click=on_start_over, key="notyet-start-over")
    frame.footer(lessons=bool(values.get("lessons")))
