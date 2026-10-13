"""All calculations for the tracker. Pure pandas; no Streamlit."""

from __future__ import annotations

import pandas as pd

from data_loader import ERROR_TYPES, split_players


def team_name(df: pd.DataFrame, team: str) -> str:
    """Display name ('Lee / Patel') for team 'A' or 'B' of a single-match frame."""
    return df[f"team_{team.lower()}"].iloc[0]


def player_teams(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, player) with the player's team letter and partner."""
    rows = []
    for match_id, match in df.groupby("match_id", sort=False):
        first = match.iloc[0]
        for team in ("A", "B"):
            names = split_players(first[f"team_{team.lower()}"])
            for name in names:
                partner = next((n for n in names if n != name), "")
                rows.append({
                    "match_id": match_id,
                    "tournament": first["tournament"],
                    "player": name,
                    "partner": partner,
                    "team": team,
                })
    return pd.DataFrame(rows, columns=["match_id", "tournament", "player", "partner", "team"])


def overview_stats(df: pd.DataFrame) -> dict:
    roster = player_teams(df)
    return {
        "matches": df["match_id"].nunique(),
        "tournaments": df["tournament"].nunique(),
        "players": roster["player"].nunique(),
        "rallies": len(df),
        "first_date": df["date"].min(),
        "last_date": df["date"].max(),
    }


def tournament_table(df: pd.DataFrame) -> pd.DataFrame:
    roster = player_teams(df)
    players = roster.groupby("tournament")["player"].nunique().rename("Players")
    table = (
        df.groupby("tournament")
        .agg(
            Start=("date", "min"),
            End=("date", "max"),
            Matches=("match_id", "nunique"),
            Rallies=("match_id", "size"),
        )
        .join(players)
        .sort_values("Start")
        .reset_index()
        .rename(columns={"tournament": "Tournament"})
    )
    table["Start"] = table["Start"].dt.date
    table["End"] = table["End"].dt.date
    return table


def player_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per player: matches played, rallies won by their team, winners and unforced errors hit."""
    roster = player_teams(df)
    matches = roster.groupby("player")["match_id"].nunique().rename("Matches")

    played = df.merge(roster[["match_id", "player", "team"]], on="match_id")
    rally_win = (
        (played["point_winner"] == played["team"])
        .groupby(played["player"])
        .mean()
        .mul(100)
        .round(1)
        .rename("Team rally win %")
    )

    by_player = df.groupby("final_shot_player")["outcome"]
    winners = by_player.apply(lambda s: (s == "winner").sum()).rename("Winners")
    errors = by_player.apply(lambda s: (s == "unforced_error").sum()).rename("Unforced errors")

    table = pd.concat([matches, rally_win, winners, errors], axis=1).fillna(0)
    table[["Matches", "Winners", "Unforced errors"]] = table[
        ["Matches", "Winners", "Unforced errors"]
    ].astype(int)
    return (
        table.rename_axis("Player")
        .reset_index()
        .sort_values(["Matches", "Player"], ascending=[False, True])
        .reset_index(drop=True)
    )


def kpis(df: pd.DataFrame, team: str, player: str | None = None) -> dict:
    """Headline numbers for one team, optionally narrowing shot counts to one player.

    `df` is the rally scope (match and game filters already applied). Rallies won is
    always a team figure; winners and unforced errors are counted on final shots.
    """
    rallies = len(df)
    won = int((df["point_winner"] == team).sum())
    shots = df[df["final_shot_team"] == team]
    if player:
        shots = shots[shots["final_shot_player"] == player]
    winners = int((shots["outcome"] == "winner").sum())
    unforced = int((shots["outcome"] == "unforced_error").sum())
    return {
        "rallies": rallies,
        "rallies_won": won,
        "rally_win_pct": round(100 * won / rallies, 1) if rallies else 0.0,
        "winners": winners,
        "unforced_errors": unforced,
        "winner_error_ratio": round(winners / unforced, 2) if unforced else None,
    }


def error_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Unforced error counts per player and error type (zeros included), long format."""
    errors = df[df["outcome"] == "unforced_error"]
    players = sorted(df["final_shot_player"].unique())
    counts = (
        errors.groupby(["final_shot_player", "error_type"])
        .size()
        .reindex(pd.MultiIndex.from_product([players, ERROR_TYPES]), fill_value=0)
    )
    counts.index.names = ["player", "error_type"]
    return counts.rename("count").reset_index()


def momentum(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cumulative rally differential (A − B) and serving rotations for one match.

    Returns (points, rotations):
      points    — one row per rally, plus a leading baseline row at momentum 0
                  (point_number = first rally − 1, so a single game starts at 0 too)
      rotations — rotation_id, serving_team, start, end (point numbers, inclusive)
    """
    if df["match_id"].nunique() > 1:
        raise ValueError("momentum() expects rallies from a single match")
    if df.empty:
        empty_points = pd.DataFrame(columns=["point_number", "momentum", "diff_change"])
        empty_rotations = pd.DataFrame(columns=["rotation_id", "serving_team", "start", "end"])
        return empty_points, empty_rotations

    points = df.sort_values("point_number").copy()
    points["diff_change"] = points["point_winner"].map({"A": 1, "B": -1})
    points["momentum"] = points["diff_change"].cumsum()

    rotations = (
        points.groupby("rotation_id")
        .agg(
            serving_team=("serving_team", "first"),
            start=("point_number", "min"),
            end=("point_number", "max"),
        )
        .reset_index()
    )

    first = int(points["point_number"].iloc[0])
    start = pd.DataFrame({"point_number": [first - 1], "momentum": [0], "diff_change": [0]})
    points = pd.concat([start, points], ignore_index=True)
    return points, rotations
