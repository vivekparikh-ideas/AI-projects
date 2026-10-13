"""Plotly figures for the tracker. No Streamlit here.

Colours are tuned for Streamlit's dark theme. Categorical colours come in a fixed
order and always mean the same thing; marker shape backs up colour on the court map.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from data_loader import ERROR_TYPES

# --- palette (dark mode) ------------------------------------------------------
BACKGROUND = "#0e1117"  # Streamlit dark background; used for 2px gaps between fills
TEXT = "#f0efec"
TEXT_MUTED = "#a3a29b"
GRID = "rgba(255,255,255,0.08)"

TEAM_COLORS = {"A": "#3987e5", "B": "#d95926"}  # blue, orange
ERROR_COLORS = {"net": "#3987e5", "wide": "#d95926", "long": "#199e70"}  # blue, orange, aqua
OUTCOME_STYLE = {
    "winner": {"label": "Winner", "color": "#199e70", "symbol": "circle", "size": 10},
    "unforced_error": {"label": "Unforced error", "color": "#e66767", "symbol": "x", "size": 10},
    "forced_error": {"label": "Forced error", "color": "#8a8986", "symbol": "diamond", "size": 8},
}

# --- pickleball court (feet, origin at net centre) --------------------------
HALF_WIDTH = 10
HALF_LENGTH = 22
KITCHEN = 7
COURT_FILL = "#1d3a4f"
KITCHEN_FILL = "#25495f"
COURT_LINE = "rgba(240,239,236,0.85)"


def _base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color=TEXT_MUTED)),
        hoverlabel=dict(bgcolor="#262730", font_color=TEXT, bordercolor="#262730"),
    )
    return fig


def _empty(message: str, height: int) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(color=TEXT_MUTED, size=14),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _base_layout(fig, height)


def court_shapes() -> list[dict]:
    """Pickleball court lines, drawn horizontally: plot x = court_y, plot y = court_x."""
    line = dict(color=COURT_LINE, width=2)
    shapes = [
        # playing surface and kitchens
        dict(type="rect", x0=-HALF_LENGTH, x1=HALF_LENGTH, y0=-HALF_WIDTH, y1=HALF_WIDTH,
             fillcolor=COURT_FILL, line=line, layer="below"),
        dict(type="rect", x0=-KITCHEN, x1=KITCHEN, y0=-HALF_WIDTH, y1=HALF_WIDTH,
             fillcolor=KITCHEN_FILL, line=line, layer="below"),
        # centre service lines (baseline to kitchen line, each side)
        dict(type="line", x0=-HALF_LENGTH, x1=-KITCHEN, y0=0, y1=0, line=line, layer="below"),
        dict(type="line", x0=KITCHEN, x1=HALF_LENGTH, y0=0, y1=0, line=line, layer="below"),
        # net, slightly past the sidelines
        dict(type="line", x0=0, x1=0, y0=-HALF_WIDTH - 1, y1=HALF_WIDTH + 1,
             line=dict(color=TEXT, width=4), layer="below"),
    ]
    return shapes


def court_map(df: pd.DataFrame, team_names: dict[str, str] | None = None) -> go.Figure:
    """Final-shot landing spots on a pickleball court, coloured and shaped by outcome."""
    height = 430
    fig = go.Figure()
    fig.update_layout(shapes=court_shapes())

    for outcome, style in OUTCOME_STYLE.items():
        shots = df[df["outcome"] == outcome]
        if shots.empty:
            continue
        error = shots["error_type"].where(shots["error_type"] != "", "—")
        fig.add_trace(go.Scatter(
            x=shots["court_y"],
            y=shots["court_x"],
            mode="markers",
            name=style["label"],
            marker=dict(color=style["color"], symbol=style["symbol"], size=style["size"],
                        line=dict(color=BACKGROUND, width=1.5)),
            customdata=list(zip(shots["point_number"], shots["final_shot_player"],
                                shots["final_shot_type"], error)),
            hovertemplate=(
                f"<b>{style['label']}</b><br>"
                "Point %{customdata[0]} · %{customdata[1]}<br>"
                "Shot: %{customdata[2]} · Error: %{customdata[3]}<br>"
                "court_x %{y:.1f} ft, court_y %{x:.1f} ft<extra></extra>"
            ),
        ))

    if team_names:
        for team, x in (("A", -HALF_LENGTH / 2), ("B", HALF_LENGTH / 2)):
            fig.add_annotation(x=x, y=HALF_WIDTH + 6.5, text=f"{team_names[team]} side",
                               showarrow=False, font=dict(color=TEXT_MUTED, size=12))

    fig.update_xaxes(range=[-30, 30], title="court_y — baseline to baseline (ft)",
                     zeroline=False, showgrid=False, color=TEXT_MUTED)
    # Headroom above the widest shots (|court_x| ≤ ~14) for the team-side labels.
    fig.update_yaxes(range=[-15, 18], title="court_x (ft)", zeroline=False, showgrid=False,
                     color=TEXT_MUTED, scaleanchor="x", scaleratio=1)
    _base_layout(fig, height)
    if not fig.data:
        fig.add_annotation(text="No shots match these filters", showarrow=False,
                           font=dict(color=TEXT_MUTED, size=14), x=0, y=-13)
    return fig


def error_bar(breakdown: pd.DataFrame) -> go.Figure:
    """Stacked bar of unforced errors per player, split by net / wide / long."""
    height = 430
    if breakdown.empty or breakdown["count"].sum() == 0:
        return _empty("No unforced errors for these filters", height)

    fig = go.Figure()
    for error_type in ERROR_TYPES:
        rows = breakdown[breakdown["error_type"] == error_type]
        fig.add_trace(go.Bar(
            x=rows["player"],
            y=rows["count"],
            name=error_type.capitalize(),
            marker=dict(color=ERROR_COLORS[error_type], line=dict(color=BACKGROUND, width=2)),
            hovertemplate=f"%{{x}}<br>{error_type.capitalize()} errors: %{{y}}<extra></extra>",
        ))

    totals = breakdown.groupby("player", sort=False)["count"].sum()
    fig.add_trace(go.Scatter(
        x=totals.index, y=totals.values, mode="text", text=totals.values,
        textposition="top center", textfont=dict(color=TEXT_MUTED), showlegend=False,
        hoverinfo="skip",
    ))

    fig.update_layout(barmode="stack", bargap=0.35, barcornerradius=4)
    fig.update_xaxes(title=None, color=TEXT_MUTED, showgrid=False)
    fig.update_yaxes(title="Unforced errors", color=TEXT_MUTED, gridcolor=GRID, zeroline=False,
                     rangemode="tozero", range=[0, max(totals.max() * 1.15, 1)])
    return _base_layout(fig, height)


def momentum_chart(points: pd.DataFrame, rotations: pd.DataFrame,
                   team_names: dict[str, str]) -> go.Figure:
    """Cumulative rally differential (A − B) with a shaded band per serving rotation."""
    height = 400
    if len(points) <= 1:
        return _empty("No rallies for these filters", height)

    fig = go.Figure()

    # Serving rotation bands, coloured by the serving team.
    shapes = []
    for row in rotations.itertuples():
        shapes.append(dict(
            type="rect", xref="x", yref="paper", x0=row.start - 0.5, x1=row.end + 0.5,
            y0=0, y1=1, fillcolor=TEAM_COLORS[row.serving_team], opacity=0.14,
            line=dict(width=0), layer="below",
        ))
    fig.update_layout(shapes=shapes)

    # Legend entries for the bands (shapes don't get legend items on their own).
    for team in ("A", "B"):
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=f"{team_names[team]} serving",
            marker=dict(symbol="square", size=12, color=TEAM_COLORS[team], opacity=0.5),
            hoverinfo="skip",
        ))

    rallies = points.iloc[1:]
    winner_name = rallies["point_winner"].map(team_names)
    fig.add_trace(go.Scatter(
        x=points["point_number"],
        y=points["momentum"],
        mode="lines+markers",
        name="Momentum (A − B)",
        line=dict(color=TEXT, width=2),
        marker=dict(size=6, color=TEXT, line=dict(color=BACKGROUND, width=1.5)),
        customdata=[["Start", "", ""]] + list(zip(
            winner_name, rallies["serving_team"].map(team_names),
            rallies["final_shot_player"] + " " + rallies["final_shot_type"] + " "
            + rallies["outcome"].str.replace("_", " "),
        )),
        hovertemplate=(
            "<b>Point %{x}</b> · momentum %{y:+d}<br>"
            "Won by: %{customdata[0]}<br>"
            "Serving: %{customdata[1]}<br>"
            "Final shot: %{customdata[2]}<extra></extra>"
        ),
    ))

    # Game boundaries.
    game_starts = rallies.groupby("game")["point_number"].min().iloc[1:]
    for game, start in game_starts.items():
        fig.add_vline(x=start - 0.5, line=dict(color=TEXT_MUTED, width=1, dash="dot"))
        fig.add_annotation(x=start - 0.5, y=1, yref="paper", text=f"Game {int(game)}",
                           showarrow=False, xanchor="left", yanchor="top",
                           font=dict(color=TEXT_MUTED, size=11))

    peak = max(abs(points["momentum"]).max(), 3) + 1
    fig.add_hline(y=0, line=dict(color=TEXT_MUTED, width=1))
    fig.add_annotation(x=0, xref="paper", y=peak, text=f"▲ {team_names['A']} ahead",
                       showarrow=False, xanchor="left", yanchor="top",
                       font=dict(color=TEXT_MUTED, size=11))
    fig.add_annotation(x=0, xref="paper", y=-peak, text=f"▼ {team_names['B']} ahead",
                       showarrow=False, xanchor="left", yanchor="bottom",
                       font=dict(color=TEXT_MUTED, size=11))

    fig.update_xaxes(title="Rally (point number)", color=TEXT_MUTED, showgrid=False,
                     zeroline=False)
    fig.update_yaxes(title="Rally differential (A − B)", color=TEXT_MUTED, gridcolor=GRID,
                     zeroline=False, range=[-peak, peak])
    fig.update_layout(hovermode="closest")
    return _base_layout(fig, height)
