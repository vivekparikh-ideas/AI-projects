"""CSV schema, validation and derived columns for the momentum tracker.

One row = one rally, described by its final shot. See README.md for the schema.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "tournament",
    "match_id",
    "date",
    "sport",
    "team_a",
    "team_b",
    "game",
    "point_number",
    "serving_team",
    "server_number",
    "final_shot_player",
    "final_shot_team",
    "final_shot_type",
    "court_x",
    "court_y",
    "outcome",
    "error_type",
    "point_winner",
]

SPORTS = {"pickleball"}
TEAMS = {"A", "B"}
SERVER_NUMBERS = {1, 2}
SHOT_TYPES = {"serve", "return", "drive", "drop", "dink", "volley", "lob", "overhead"}
OUTCOMES = {"winner", "unforced_error", "forced_error"}
ERROR_TYPES = ["net", "wide", "long"]

# Columns that must not change between rows of the same match.
MATCH_LEVEL_COLUMNS = ["tournament", "date", "sport", "team_a", "team_b"]

# Cap the number of row-level messages so a badly broken file stays readable.
MAX_ERRORS = 25


def split_players(team: str) -> list[str]:
    """'Lee / Patel' -> ['Lee', 'Patel']."""
    return [name.strip() for name in str(team).split("/") if name.strip()]


def _row_label(index: int) -> str:
    # +2: one for the header line, one because CSV lines are 1-based.
    return f"Row {index + 2}"


def _check_allowed(df: pd.DataFrame, column: str, allowed: set, errors: list[str]) -> None:
    bad = df[~df[column].isin(allowed)]
    for idx, value in bad[column].items():
        errors.append(
            f"{_row_label(idx)}: {column} is '{value}' (allowed: {', '.join(sorted(map(str, allowed)))})"
        )


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    """Clean and validate a raw DataFrame.

    Returns (clean_df, []) on success, or (None, errors) with readable messages.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    if df.empty:
        return None, ["The file has no data rows."]

    df = df[REQUIRED_COLUMNS].copy()
    errors: list[str] = []

    # --- normalise text ---------------------------------------------------
    text_cols = [
        "tournament", "match_id", "sport", "team_a", "team_b", "serving_team",
        "final_shot_player", "final_shot_team", "final_shot_type", "outcome",
        "error_type", "point_winner",
    ]
    for col in text_cols:
        df[col] = df[col].fillna("").astype(str).str.strip()
    for col in ["sport", "final_shot_type", "outcome", "error_type"]:
        df[col] = df[col].str.lower()
    for col in ["serving_team", "final_shot_team", "point_winner"]:
        df[col] = df[col].str.upper()

    for col in ["tournament", "match_id", "team_a", "team_b", "final_shot_player"]:
        for idx in df.index[df[col] == ""]:
            errors.append(f"{_row_label(idx)}: {col} is empty")

    # --- types --------------------------------------------------------------
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    for idx in df.index[df["date"].isna()]:
        errors.append(f"{_row_label(idx)}: date must be YYYY-MM-DD")

    for col in ["game", "point_number", "server_number", "court_x", "court_y"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        for idx in df.index[df[col].isna()]:
            errors.append(f"{_row_label(idx)}: {col} must be a number")

    if errors:
        return None, errors[:MAX_ERRORS]

    for col in ["game", "point_number", "server_number"]:
        not_int = df[col] % 1 != 0
        for idx in df.index[not_int]:
            errors.append(f"{_row_label(idx)}: {col} must be a whole number")
    for idx in df.index[df["game"] < 1]:
        errors.append(f"{_row_label(idx)}: game must be 1 or higher")
    if errors:
        return None, errors[:MAX_ERRORS]
    for col in ["game", "point_number", "server_number"]:
        df[col] = df[col].astype(int)

    # --- allowed values -----------------------------------------------------
    _check_allowed(df, "sport", SPORTS, errors)
    _check_allowed(df, "serving_team", TEAMS, errors)
    _check_allowed(df, "server_number", SERVER_NUMBERS, errors)
    _check_allowed(df, "final_shot_team", TEAMS, errors)
    _check_allowed(df, "final_shot_type", SHOT_TYPES, errors)
    _check_allowed(df, "outcome", OUTCOMES, errors)
    _check_allowed(df, "point_winner", TEAMS, errors)
    _check_allowed(df, "error_type", set(ERROR_TYPES) | {""}, errors)
    if errors:
        return None, errors[:MAX_ERRORS]

    # --- cross-column consistency -----------------------------------------
    is_ue = df["outcome"] == "unforced_error"
    for idx in df.index[is_ue & (df["error_type"] == "")]:
        errors.append(f"{_row_label(idx)}: unforced_error needs an error_type (net, wide or long)")
    for idx in df.index[~is_ue & (df["error_type"] != "")]:
        errors.append(
            f"{_row_label(idx)}: error_type must be blank when outcome is '{df.at[idx, 'outcome']}'"
        )

    is_winner = df["outcome"] == "winner"
    for idx in df.index[is_winner & (df["point_winner"] != df["final_shot_team"])]:
        errors.append(
            f"{_row_label(idx)}: outcome is 'winner' but point_winner "
            f"({df.at[idx, 'point_winner']}) ≠ final_shot_team ({df.at[idx, 'final_shot_team']})"
        )
    for idx in df.index[~is_winner & (df["point_winner"] == df["final_shot_team"])]:
        errors.append(
            f"{_row_label(idx)}: outcome is '{df.at[idx, 'outcome']}' so point_winner "
            f"must be the other team, not {df.at[idx, 'point_winner']}"
        )

    for idx, row in df.iterrows():
        roster = row["team_a"] if row["final_shot_team"] == "A" else row["team_b"]
        if row["final_shot_player"] not in split_players(roster):
            errors.append(
                f"{_row_label(idx)}: final_shot_player '{row['final_shot_player']}' "
                f"is not on team {row['final_shot_team']} ({roster})"
            )

    # --- match-level checks ------------------------------------------------
    for match_id, match in df.groupby("match_id", sort=False):
        for col in MATCH_LEVEL_COLUMNS:
            if match[col].nunique() > 1:
                errors.append(f"Match {match_id}: {col} differs between rows")
        points = match["point_number"]
        if points.duplicated().any():
            dupes = sorted(points[points.duplicated()].unique())
            errors.append(f"Match {match_id}: duplicate point_number(s) {dupes}")
        elif sorted(points) != list(range(1, len(points) + 1)):
            errors.append(f"Match {match_id}: point_number must run 1, 2, 3… with no gaps")

    if errors:
        return None, errors[:MAX_ERRORS]

    df = df.sort_values(["date", "match_id", "point_number"]).reset_index(drop=True)
    return add_rotations(df), []


def load_csv(file) -> tuple[pd.DataFrame | None, list[str]]:
    """Read a CSV path or file-like object and validate it."""
    try:
        raw = pd.read_csv(file, dtype=str, keep_default_na=False)
    except Exception as exc:  # malformed file, wrong encoding, etc.
        return None, [f"Could not read the file as CSV: {exc}"]
    return validate(raw)


def add_rotations(df: pd.DataFrame) -> pd.DataFrame:
    """Add rotation_id: 1, 2, 3… per match, +1 at every side-out."""
    df = df.sort_values(["match_id", "point_number"]).copy()
    side_out = df["serving_team"] != df.groupby("match_id")["serving_team"].shift()
    df["rotation_id"] = side_out.astype(int).groupby(df["match_id"]).cumsum()
    return df.sort_values(["date", "match_id", "point_number"]).reset_index(drop=True)
