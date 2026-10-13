import io

import pandas as pd
import pytest

from data_loader import add_rotations, load_csv, split_players, validate


def errors_for(raw):
    df, errors = validate(raw)
    assert df is None
    return " | ".join(errors)


def test_valid_match_loads(match):
    assert len(match) == 8
    assert match["point_number"].tolist() == list(range(1, 9))
    assert match["date"].dtype.kind == "M"
    assert match["court_x"].dtype.kind == "f"


def test_load_csv_from_file_object(raw_match):
    buffer = io.StringIO(raw_match.to_csv(index=False))
    df, errors = load_csv(buffer)
    assert errors == []
    assert len(df) == 8


def test_load_csv_unreadable_file():
    df, errors = load_csv(io.BytesIO(b"\x00\x01\x02"))
    assert df is None
    assert errors


def test_missing_column_is_named(raw_match):
    message = errors_for(raw_match.drop(columns=["court_x", "outcome"]))
    assert "court_x" in message and "outcome" in message


def test_empty_file(raw_match):
    assert "no data rows" in errors_for(raw_match.iloc[0:0])


def test_text_is_normalised(raw_match):
    raw_match.loc[0, "outcome"] = " Winner "
    raw_match.loc[0, "serving_team"] = "a"
    df, errors = validate(raw_match)
    assert errors == []
    assert df.loc[0, "outcome"] == "winner"
    assert df.loc[0, "serving_team"] == "A"


@pytest.mark.parametrize("column, value, expected", [
    ("outcome", "foo", "outcome is 'foo'"),
    ("court_x", "abc", "court_x must be a number"),
    ("date", "14/09/2026", "date must be YYYY-MM-DD"),
    ("sport", "tennis", "sport is 'tennis'"),
    ("server_number", "3", "server_number is '3'"),
    ("final_shot_type", "smash", "final_shot_type is 'smash'"),
    ("game", "1.5", "game must be a whole number"),
])
def test_bad_values_are_flagged_with_row(raw_match, column, value, expected):
    raw_match.loc[2, column] = value
    message = errors_for(raw_match)
    assert expected in message
    assert "Row 4" in message  # index 2 → line 4 (header is line 1)


def test_error_type_required_for_unforced_error(raw_match):
    raw_match.loc[1, "error_type"] = ""
    assert "needs an error_type" in errors_for(raw_match)


def test_error_type_must_be_blank_otherwise(raw_match):
    raw_match.loc[0, "error_type"] = "net"  # row 0 is a winner
    assert "error_type must be blank" in errors_for(raw_match)


def test_winner_must_be_won_by_hitting_team(raw_match):
    raw_match.loc[0, "point_winner"] = "B"
    assert "point_winner (B) ≠ final_shot_team (A)" in errors_for(raw_match)


def test_error_must_be_won_by_other_team(raw_match):
    raw_match.loc[1, "point_winner"] = "B"  # Okafor (B) erred, so A must win
    assert "must be the other team" in errors_for(raw_match)


def test_player_must_belong_to_team(raw_match):
    raw_match.loc[0, "final_shot_player"] = "Cruz"  # Cruz is on B, row says A
    assert "'Cruz' is not on team A" in errors_for(raw_match)


def test_duplicate_point_numbers(raw_match):
    raw_match.loc[1, "point_number"] = "1"
    assert "duplicate point_number" in errors_for(raw_match)


def test_gap_in_point_numbers(raw_match):
    raw_match.loc[7, "point_number"] = "10"
    assert "no gaps" in errors_for(raw_match)


def test_match_level_columns_must_be_consistent(raw_match):
    raw_match.loc[3, "tournament"] = "Other Open"
    assert "tournament differs" in errors_for(raw_match)


def test_rotations_start_new_on_each_side_out(match):
    assert match["rotation_id"].tolist() == [1, 1, 1, 2, 2, 2, 3, 3]


def test_rotations_restart_per_match(two_matches):
    second = two_matches[two_matches["match_id"] == "M002"]
    assert second["rotation_id"].tolist() == [1, 1, 2]


def test_one_team_serving_all_match_is_one_rotation():
    df = pd.DataFrame({
        "match_id": ["M1"] * 4,
        "point_number": [1, 2, 3, 4],
        "serving_team": ["A"] * 4,
        "date": pd.to_datetime(["2026-01-01"] * 4),
    })
    assert add_rotations(df)["rotation_id"].tolist() == [1, 1, 1, 1]


def test_split_players():
    assert split_players("Lee / Patel") == ["Lee", "Patel"]
    assert split_players("Lee/Patel") == ["Lee", "Patel"]
