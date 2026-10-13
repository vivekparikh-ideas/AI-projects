import pytest

import metrics


def test_momentum_matches_hand_calculation(match):
    points, _ = metrics.momentum(match)
    assert points["point_number"].tolist() == list(range(0, 9))
    assert points["momentum"].tolist() == [0, 1, 2, 1, 0, 1, 0, 1, 0]


def test_momentum_rotation_bands(match):
    _, rotations = metrics.momentum(match)
    assert rotations[["serving_team", "start", "end"]].values.tolist() == [
        ["A", 1, 3], ["B", 4, 6], ["A", 7, 8],
    ]


def test_momentum_for_a_single_game_starts_at_zero(match):
    points, rotations = metrics.momentum(match[match["game"] == 2])
    assert points["point_number"].tolist() == [6, 7, 8]
    assert points["momentum"].tolist() == [0, 1, 0]
    assert len(rotations) == 1


def test_momentum_rejects_multiple_matches(two_matches):
    with pytest.raises(ValueError):
        metrics.momentum(two_matches)


def test_momentum_empty(match):
    points, rotations = metrics.momentum(match.iloc[0:0])
    assert points.empty and rotations.empty


def test_kpis_per_team(match):
    a = metrics.kpis(match, "A")
    assert a == {
        "rallies": 8, "rallies_won": 4, "rally_win_pct": 50.0,
        "winners": 2, "unforced_errors": 2, "winner_error_ratio": 1.0,
    }
    b = metrics.kpis(match, "B")
    assert (b["rallies_won"], b["winners"], b["unforced_errors"]) == (4, 1, 2)


def test_kpis_for_one_player(match):
    k = metrics.kpis(match, "A", player="Patel")
    assert k["rallies_won"] == 4  # still a team figure
    assert (k["winners"], k["unforced_errors"]) == (1, 1)


def test_kpis_empty_scope_returns_zeros(match):
    k = metrics.kpis(match.iloc[0:0], "A")
    assert k["rallies"] == 0 and k["rally_win_pct"] == 0.0
    assert k["winner_error_ratio"] is None


def test_error_breakdown_counts_only_unforced_errors(match):
    table = metrics.error_breakdown(match).set_index(["player", "error_type"])["count"]
    assert table[("Okafor", "net")] == 1
    assert table[("Okafor", "long")] == 1
    assert table[("Lee", "wide")] == 1
    assert table[("Patel", "long")] == 1
    assert table.sum() == 4  # Patel's forced error is excluded
    # every player who hit a final shot appears with all three types, zeros included
    assert len(table) == 4 * 3
    assert table[("Cruz", "net")] == 0


def test_overview_stats(two_matches):
    stats = metrics.overview_stats(two_matches)
    assert stats["matches"] == 2
    assert stats["tournaments"] == 2
    assert stats["players"] == 7  # Lee plays in both matches, counted once
    assert stats["rallies"] == 11


def test_player_table(two_matches):
    table = metrics.player_table(two_matches).set_index("Player")
    assert table.loc["Lee", "Matches"] == 2
    assert table.loc["Okafor", "Unforced errors"] == 2
    assert table.loc["Patel", "Winners"] == 1
    # Kim's team (B in M002) won 1 of 3 rallies
    assert table.loc["Kim", "Team rally win %"] == pytest.approx(33.3)
    assert table.index.is_unique


def test_tournament_table(two_matches):
    table = metrics.tournament_table(two_matches).set_index("Tournament")
    assert table.loc["Austin Open", "Rallies"] == 8
    assert table.loc["Desert Classic", "Players"] == 4
    assert table.index.tolist() == ["Austin Open", "Desert Classic"]  # sorted by date


def test_team_name(match):
    assert metrics.team_name(match, "A") == "Lee / Patel"
    assert metrics.team_name(match, "B") == "Cruz / Okafor"
