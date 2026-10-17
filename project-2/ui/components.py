"""HTML building blocks shared by the screens: logo, Tilly, tile bars, the staircase, math text.

Every piece of dynamic text passes through esc() before it is placed in HTML.
"""
import html

import streamlit as st

TEAL, SUN, TOMATO, GRAPE, BLUE = "#1FA595", "#F4B740", "#E8553D", "#7D55E0", "#3550D6"
INK, MUTED, LINE = "#1C2541", "#59627A", "#D9E0EC"
TILE_COLORS = [SUN, TOMATO, GRAPE, TEAL]
CHECK_SVG = ('<svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
             'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 12 10 17 19 7"></polyline></svg>')
LENS_SVG = ('<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3550D6" stroke-width="2.4" '
            'stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"></circle><line x1="15.5" y1="15.5" x2="21" y2="21"></line></svg>')
PEOPLE_SVG = ('<svg aria-hidden="true" width="40" height="34" viewBox="0 0 40 34" fill="none" stroke="#15796D" stroke-width="2.4" '
              'stroke-linecap="round" stroke-linejoin="round" style="flex:none"><circle cx="12" cy="8" r="5"></circle>'
              '<path d="M3 31v-5a9 9 0 0 1 18 0v5"></path><circle cx="29" cy="14" r="4"></circle><path d="M22 31v-3a7 7 0 0 1 14 0v3"></path></svg>')
INFO_SVG = ('<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8A5A00" stroke-width="2.2" '
            'stroke-linecap="round" style="flex:none"><circle cx="12" cy="12" r="9"></circle><line x1="12" y1="11" x2="12" y2="16"></line>'
            '<line x1="12" y1="8" x2="12" y2="8"></line></svg>')
ARROW_SVG = ('<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#59627A" stroke-width="2.6" '
             'stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="13 6 19 12 13 18"></polyline></svg>')


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def show(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def to_markdown_math(text: str) -> str:
    """Source problems mark math as LaTeX \\( \\); Streamlit renders $ $. Literal dollar signs are escaped first."""
    s = (text or "").replace("$", r"\$")
    return s.replace(r"\(", "$").replace(r"\)", "$").replace(r"\[", "$$").replace(r"\]", "$$")


def truncate(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def logo() -> str:
    bars = [(6, TEAL, False), (10, SUN, False), (14, None, True), (18, GRAPE, False)]
    parts = "".join(
        f'<div style="width:6px;height:{h}px;border-radius:2px;'
        + ("border:1.5px dashed #59627A;box-sizing:border-box;" if dashed else f"background:{c};") + '"></div>'
        for h, c, dashed in bars)
    return (f'<div style="display:flex;align-items:center;gap:10px"><div aria-hidden="true" style="display:flex;align-items:flex-end;gap:2px;height:18px">{parts}</div>'
            '<span style="font-family:Fredoka,sans-serif;font-weight:700;font-size:21px;color:#1C2541">Gap Finder</span></div>')


def tilly(px: int = 56, mood: str = "happy", rotate: int = -8) -> str:
    """Tilly the tile. Moods: happy, cheer, curious, flat."""
    h, eye, pupil = int(px * 0.8), max(7, px // 6), max(3, px // 13)
    gap = max(7, px // 6)
    if mood == "cheer":
        eyes = f'<div style="width:{eye}px;height:{eye // 2}px;border-top:3px solid #fff;border-radius:{eye}px {eye}px 0 0"></div>' * 2
        mouth = f'<div style="width:{px // 3}px;height:{px // 7}px;background:#fff;border-radius:0 0 {px}px {px}px"></div>'
    else:
        align = {"curious": "flex-start", "flat": "flex-end"}.get(mood, "center")
        eyes = (f'<div style="width:{eye}px;height:{eye}px;border-radius:50%;background:#fff;display:flex;align-items:{align};'
                f'justify-content:center"><div style="width:{pupil}px;height:{pupil}px;border-radius:50%;background:{INK}"></div></div>') * 2
        mouth = {"curious": f'<div style="width:{px // 5}px;height:{px // 5}px;border-radius:50%;border:3px solid #fff;box-sizing:border-box"></div>',
                 "flat": f'<div style="width:{px // 4}px;height:3px;border-radius:2px;background:#fff"></div>'}.get(
            mood, f'<div style="width:{px // 4}px;height:{px // 9}px;border-bottom:3px solid #fff;border-radius:0 0 {px}px {px}px"></div>')
    return (f'<div aria-hidden="true" style="flex:none;width:{px}px;height:{h}px;border-radius:{px // 4}px;background:{TEAL};'
            f'box-shadow:0 {max(3, px // 18)}px 0 #15796D;display:flex;flex-direction:column;align-items:center;justify-content:center;'
            f'gap:{max(3, px // 14)}px;transform:rotate({rotate}deg)"><div style="display:flex;gap:{gap}px">{eyes}</div>{mouth}</div>')


def tile_bar(done: int, total: int, color: str = TOMATO, height: int = 12, current: int | None = None, label: str = "") -> str:
    tiles = []
    for i in range(total):
        if i < done:
            style = f"background:{color}"
        elif current is not None and i == current:
            style = f"border:2px dashed {color};box-sizing:border-box;background:#fff"
        else:
            style = f"background:#fff;border:1.5px solid {LINE};box-sizing:border-box"
        tiles.append(f'<div style="flex:1;height:{height}px;border-radius:4px;{style}"></div>')
    return f'<div role="img" aria-label="{esc(label)}" style="display:flex;gap:4px">{"".join(tiles)}</div>'


def staircase() -> str:
    """Landing option B: Kindergarten to Grade 8, one missing step, Tilly on top."""
    steps = [(36, TEAL, "#fff", "1+1"), (62, SUN, INK, "×"), (88, None, None, None), (114, TOMATO, "#fff", "½"), (140, GRAPE, "#fff", "2x")]
    cols = []
    for height, bg, fg, sym in steps:
        if bg is None:
            cols.append(f'<div style="flex:1;height:{height}px;border-radius:9px 9px 4px 4px;border:2.5px dashed {BLUE};box-sizing:border-box;'
                        f'background:#EEF2FF;display:flex;justify-content:center;padding-top:8px">{LENS_SVG}</div>')
        else:
            cols.append(f'<div style="flex:1;height:{height}px;border-radius:9px 9px 4px 4px;background:{bg};color:{fg};display:flex;'
                        f'justify-content:center;padding-top:7px;box-sizing:border-box;font-family:Fredoka,sans-serif;font-weight:600;font-size:17px">{sym}</div>')
    cols.append(f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px">{tilly(44, "happy", -10)}'
                f'<div style="width:100%;height:156px;border-radius:9px 9px 4px 4px;background:{BLUE};color:#fff;display:flex;justify-content:center;'
                'padding-top:7px;box-sizing:border-box;font-family:Fredoka,sans-serif;font-weight:600;font-size:16px">x²</div></div>')
    return (f'<div class="gf-card" role="img" aria-label="A staircase of math skills from kindergarten to grade 8 with one step missing">'
            f'<div style="display:flex;align-items:flex-end;gap:6px;height:196px">{"".join(cols)}</div>'
            '<div style="display:flex;justify-content:space-between;font-size:11.5px;color:#59627A;font-weight:500">'
            '<span>Kindergarten</span><span>Grade 8</span></div></div>')


def together_note() -> str:
    return (f'<div class="gf-note together">{PEOPLE_SVG}<span><b>Do this together.</b> You and your child, side by side, '
            'for about 5 minutes. Grab a pencil and paper.</span></div>')


def coverage_note() -> str:
    return f'<div class="gf-note coverage">{INFO_SVG}<span><b>Right now: fraction homework, grades 3–6.</b> More topics coming.</span></div>'


def role_line() -> str:
    return ('<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px">'
            '<span class="gf-chip" style="background:#E3F5F2;color:#15665C">Child solves on paper</span>'
            f'{ARROW_SVG}<span class="gf-chip" style="background:#EEF2FF;color:#2238A8">You type their answer</span></div>')


def checklist(items: list[tuple[str, str]], done: set[str], current: str | None, details: dict[str, str]) -> str:
    rows = []
    for key, label in items:
        detail = f' <span class="gf-code">{esc(details[key])}</span>' if details.get(key) else ""
        if key in done:
            box = f'<span style="flex:none;width:26px;height:26px;border-radius:8px;background:#1E8E5A;display:flex;align-items:center;justify-content:center">{CHECK_SVG}</span>'
            rows.append(f'<li style="display:flex;align-items:center;gap:12px">{box}<span>{esc(label)}{detail}</span></li>')
        elif key == current:
            box = '<span style="flex:none;width:26px;height:26px;border-radius:8px;border:2.5px dashed #1FA595;box-sizing:border-box;background:#E3F5F2"></span>'
            rows.append(f'<li style="display:flex;align-items:center;gap:12px;font-weight:600">{box}<span>{esc(label)}…</span></li>')
        else:
            box = '<span style="flex:none;width:26px;height:26px;border-radius:8px;border:1.5px solid #D9E0EC;box-sizing:border-box"></span>'
            rows.append(f'<li style="display:flex;align-items:center;gap:12px;color:#8890A4">{box}<span>{esc(label)}</span></li>')
    return f'<ol class="gf-card" aria-live="polite" style="list-style:none;margin:0;gap:14px;font-size:15px">{"".join(rows)}</ol>'
