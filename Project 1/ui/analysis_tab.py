"""Tab 2: filter bar, KPI rows and the three charts for one match."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import metrics

ALL = "All"
BOTH_TEAMS = "Both teams"


def render(df: pd.DataFrame | None) -> None:
    if df is None or df.empty:
        st.info("No valid data loaded. Upload a CSV in **Upload & Overview** first.")
        return

    match_df, team, player = _filters(df)
    team_names = {"A": metrics.team_name(match_df, "A"), "B": metrics.team_name(match_df, "B")}

    # Charts that describe shots narrow to the selected team/player; the momentum
    # line and rally counts are inherently A-vs-B, so they use the whole rally scope.
    shots = match_df
    if team:
        shots = shots[shots["final_shot_team"] == team]
    if player:
        shots = shots[shots["final_shot_player"] == player]

    _kpi_rows(match_df, team, player, team_names)

    st.divider()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Court map: final-shot placement")
        st.plotly_chart(charts.court_map(shots, team_names), width="stretch")
    with right:
        st.subheader("Unforced errors by type")
        st.plotly_chart(charts.error_bar(metrics.error_breakdown(shots)), width="stretch")

    st.subheader("Match momentum timeline")
    points, rotations = metrics.momentum(match_df)
    st.plotly_chart(charts.momentum_chart(points, rotations, team_names), width="stretch")
    st.caption(
        "Each rally won moves the line one step: up for "
        f"{team_names['A']}, down for {team_names['B']}. Shaded bands show who was serving; "
        "every rally counts, including side-outs. Team and player filters don't apply here."
    )


def _filters(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None, str | None]:
    """Filter bar. Returns (rallies in the selected match/game, team letter, player)."""
    cols = st.columns([1, 3, 2, 2, 1])

    sport = cols[0].selectbox("Sport", sorted(df["sport"].unique()))
    df = df[df["sport"] == sport]

    matches = df.drop_duplicates("match_id")
    labels = {
        f"{row.match_id} · {row.tournament} · {row.team_a} vs {row.team_b}": row.match_id
        for row in matches.itertuples()
    }
    match_label = cols[1].selectbox("Match", list(labels))
    match_df = df[df["match_id"] == labels[match_label]]

    team_names = {"A": metrics.team_name(match_df, "A"), "B": metrics.team_name(match_df, "B")}
    team_label = cols[2].selectbox("Team", [BOTH_TEAMS, team_names["A"], team_names["B"]])
    team = next((t for t, name in team_names.items() if name == team_label), None)

    roster = metrics.player_teams(match_df)
    if team:
        roster = roster[roster["team"] == team]
    player = cols[3].selectbox("Player", [ALL] + roster["player"].tolist())

    games = sorted(match_df["game"].unique())
    game = cols[4].selectbox("Game", [ALL] + [int(g) for g in games])
    if game != ALL:
        match_df = match_df[match_df["game"] == game]

    return match_df, team, (None if player == ALL else player)


def _kpi_rows(match_df: pd.DataFrame, team: str | None, player: str | None,
              team_names: dict[str, str]) -> None:
    for t in [team] if team else ["A", "B"]:
        k = metrics.kpis(match_df, t, player)
        label = team_names[t] + (f" · {player}" if player else "")
        st.markdown(f"##### {label}")
        c = st.columns(4)
        c[0].metric("Rallies won", f"{k['rallies_won']} / {k['rallies']}",
                    help="Team figure, even when a player is selected.")
        c[1].metric("Rally win rate", f"{k['rally_win_pct']:.1f}%")
        c[2].metric("Winners", k["winners"])
        c[3].metric(
            "Unforced errors", k["unforced_errors"],
            help="Winner : error ratio = "
            + (f"{k['winner_error_ratio']:.2f}" if k["winner_error_ratio"] is not None else "n/a"),
        )
