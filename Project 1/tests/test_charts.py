import plotly.graph_objects as go

import charts
import metrics

TEAMS = {"A": "Lee / Patel", "B": "Cruz / Okafor"}


def trace_names(fig):
    return [t.name for t in fig.data]


def test_court_map_traces_and_court_lines(match):
    fig = charts.court_map(match, TEAMS)
    assert isinstance(fig, go.Figure)
    assert trace_names(fig) == ["Winner", "Unforced error", "Forced error"]
    assert len(fig.layout.shapes) == len(charts.court_shapes())
    winners = fig.data[0]
    assert len(winners.x) == 3


def test_court_map_draws_court_y_along_the_long_axis(match):
    fig = charts.court_map(match.head(1))
    assert fig.data[0].x[0] == match.loc[0, "court_y"]
    assert fig.data[0].y[0] == match.loc[0, "court_x"]


def test_court_map_empty(match):
    fig = charts.court_map(match.iloc[0:0])
    assert len(fig.data) == 0
    assert fig.layout.shapes  # the court is still drawn


def test_error_bar_has_three_stacked_types(match):
    fig = charts.error_bar(metrics.error_breakdown(match))
    bars = [t for t in fig.data if isinstance(t, go.Bar)]
    assert [b.name for b in bars] == ["Net", "Wide", "Long"]
    assert fig.layout.barmode == "stack"


def test_error_bar_empty(match):
    winners_only = match[match["outcome"] == "winner"]
    fig = charts.error_bar(metrics.error_breakdown(winners_only))
    assert len(fig.data) == 0


def test_momentum_chart_line_and_bands(match):
    points, rotations = metrics.momentum(match)
    fig = charts.momentum_chart(points, rotations, TEAMS)
    line = next(t for t in fig.data if t.name == "Momentum (A − B)")
    assert list(line.y) == [0, 1, 2, 1, 0, 1, 0, 1, 0]
    bands = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(bands) == 3
    assert "Lee / Patel serving" in trace_names(fig)


def test_momentum_chart_empty(match):
    points, rotations = metrics.momentum(match.iloc[0:0])
    fig = charts.momentum_chart(points, rotations, TEAMS)
    assert len(fig.data) == 0
