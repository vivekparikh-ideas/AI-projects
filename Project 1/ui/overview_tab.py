"""Tab 1: upload a CSV and see what the dataset covers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import metrics
from data_loader import load_csv

ABOUT = """
**Match Momentum Tracker** is a match-play performance analyzer for doubles pickleball.
Each row of the dataset is one rally, described by its **final shot**: who hit it,
where it landed, and whether it was a winner or an error.

Use it to see **why a team won or lost key stretches of a match**:

- **Court map:** where winners and unforced errors land
- **Error breakdown:** whether each player misses into the net, wide, or long
- **Momentum timeline:** the running rally differential, shaded by serving rotation
"""


def render(load_sample) -> pd.DataFrame | None:
    """Draw Tab 1 and return the active dataset (upload, or sample), or None if invalid."""
    st.markdown(ABOUT)

    uploaded = st.file_uploader("Upload a match CSV", type=["csv"],
                                help="See 'CSV format' below for the required columns.")

    if uploaded is not None:
        df, errors = load_csv(uploaded)
        if errors:
            st.error(f"**{uploaded.name}** couldn't be loaded. Fix these issues and upload again:")
            st.markdown("\n".join(f"- {e}" for e in errors))
            _schema_help()
            return None
        st.success(f"Loaded **{uploaded.name}**: {len(df)} rallies.")
    else:
        df, errors = load_sample()
        if errors:  # only if the bundled file has been edited into an invalid state
            st.error("The bundled sample dataset is invalid: " + "; ".join(errors))
            return None
        st.info("Showing the bundled **sample dataset**. Upload your own CSV to replace it.")

    _overview(df)
    _schema_help()
    return df


def _overview(df) -> None:
    stats = metrics.overview_stats(df)

    st.subheader("Dataset overview")
    cols = st.columns(4)
    cols[0].metric("Matches", stats["matches"])
    cols[1].metric("Tournaments", stats["tournaments"])
    cols[2].metric("Players", stats["players"])
    cols[3].metric("Rallies tracked", stats["rallies"])
    st.caption(
        f"Matches from {stats['first_date']:%d %b %Y} to {stats['last_date']:%d %b %Y}"
    )

    left, right = st.columns([2, 3])
    with left:
        st.markdown("##### Tournaments")
        st.dataframe(metrics.tournament_table(df), hide_index=True, width="stretch")
    with right:
        st.markdown("##### Players")
        st.dataframe(
            metrics.player_table(df),
            hide_index=True,
            width="stretch",
            column_config={
                "Team rally win %": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0, max_value=100
                ),
            },
        )


def _schema_help() -> None:
    with st.expander("CSV format"):
        st.markdown(
            """
One row per rally (final shot only). Columns:

| Column | Values |
|---|---|
| `tournament`, `match_id` | text |
| `date` | `YYYY-MM-DD` |
| `sport` | `pickleball` |
| `team_a`, `team_b` | `"Name1 / Name2"` |
| `game`, `point_number` | integers; `point_number` runs 1, 2, 3… across the match |
| `serving_team` | `A` / `B` |
| `server_number` | `1` / `2` |
| `final_shot_player`, `final_shot_team` | a player from that team, `A` / `B` |
| `final_shot_type` | serve, return, drive, drop, dink, volley, lob, overhead |
| `court_x`, `court_y` | feet from net centre; court is ±10 wide, ±22 long |
| `outcome` | winner, unforced_error, forced_error |
| `error_type` | net, wide, long (only for unforced_error) |
| `point_winner` | `A` / `B` |
"""
        )
