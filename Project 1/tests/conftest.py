import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_loader import REQUIRED_COLUMNS, validate  # noqa: E402

SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_matches.csv"

# A hand-built 8-rally match with known answers.
#   point  serve  winner  final shot                       momentum  rotation
#     1    A2     A       Patel winner                        +1        1
#     2    A2     A       Okafor UE net                       +2        1
#     3    A2     B       Lee UE wide         (side-out)      +1        1
#     4    B1     B       Cruz winner                          0        2
#     5    B1     A       Okafor UE long                      +1        2
#     6    B2     B       Patel UE long                        0        2
#     7    A1     A       Lee winner          (game 2)        +1        3
#     8    A1     B       Patel forced error                   0        3
RALLIES = [
    # game, point, serving_team, server, player, team, shot, x, y, outcome, error, winner
    (1, 1, "A", 2, "Patel", "A", "drive", 6.1, 19.4, "winner", "", "A"),
    (1, 2, "A", 2, "Okafor", "B", "dink", -1.8, 1.2, "unforced_error", "net", "A"),
    (1, 3, "A", 2, "Lee", "A", "drop", 11.6, 5.3, "unforced_error", "wide", "B"),
    (1, 4, "B", 1, "Cruz", "B", "volley", -3.4, -12.7, "winner", "", "B"),
    (1, 5, "B", 1, "Okafor", "B", "lob", 2.0, -24.8, "unforced_error", "long", "A"),
    (1, 6, "B", 2, "Patel", "A", "drive", 1.0, 25.0, "unforced_error", "long", "B"),
    (2, 7, "A", 1, "Lee", "A", "overhead", 4.0, 15.0, "winner", "", "A"),
    (2, 8, "A", 1, "Patel", "A", "return", -7.5, 8.9, "forced_error", "", "B"),
]


def make_rows(match_id="M001", rallies=RALLIES, tournament="Austin Open",
              date="2026-09-14", team_a="Lee / Patel", team_b="Cruz / Okafor"):
    rows = []
    for game, point, serve, server, player, team, shot, x, y, outcome, error, winner in rallies:
        rows.append({
            "tournament": tournament, "match_id": match_id, "date": date,
            "sport": "pickleball", "team_a": team_a, "team_b": team_b,
            "game": game, "point_number": point, "serving_team": serve,
            "server_number": server, "final_shot_player": player, "final_shot_team": team,
            "final_shot_type": shot, "court_x": x, "court_y": y, "outcome": outcome,
            "error_type": error, "point_winner": winner,
        })
    return rows


@pytest.fixture
def raw_match() -> pd.DataFrame:
    """Unvalidated raw frame, as if read from CSV (all strings)."""
    return pd.DataFrame(make_rows(), columns=REQUIRED_COLUMNS).astype(str)


@pytest.fixture
def match(raw_match) -> pd.DataFrame:
    df, errors = validate(raw_match)
    assert errors == []
    return df


@pytest.fixture
def two_matches() -> pd.DataFrame:
    rows = make_rows() + make_rows(
        match_id="M002", tournament="Desert Classic", date="2026-09-20",
        team_a="Nguyen / Rossi", team_b="Lee / Kim",
        rallies=[
            (1, 1, "B", 2, "Kim", "B", "drive", 0.0, -10.0, "winner", "", "B"),
            (1, 2, "B", 2, "Lee", "B", "dink", 0.5, 1.0, "unforced_error", "net", "A"),
            (1, 3, "A", 1, "Rossi", "A", "volley", 3.0, 10.0, "winner", "", "A"),
        ],
    )
    df, errors = validate(pd.DataFrame(rows, columns=REQUIRED_COLUMNS).astype(str))
    assert errors == []
    return df
