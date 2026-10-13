"""End-to-end smoke tests: run the real app with Streamlit's AppTest."""

from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, SAMPLE_CSV
from data_loader import load_csv

APP = str(PROJECT_ROOT / "app.py")


def test_sample_csv_is_valid():
    df, errors = load_csv(SAMPLE_CSV)
    assert errors == []
    assert df["match_id"].nunique() >= 2


def test_app_renders_both_tabs_with_sample_data():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert len(at.tabs) == 2
    assert [m.label for m in at.metric][:4] == ["Matches", "Tournaments", "Players", "Rallies tracked"]
    assert len(at.get("plotly_chart")) == 3


def test_app_filters_change_without_errors():
    at = AppTest.from_file(APP, default_timeout=30).run()
    # selectbox order: sport, match, team, player, game
    at.selectbox[1].select_index(1).run()   # second match
    assert not at.exception
    at.selectbox[2].select_index(1).run()   # one team
    at.selectbox[3].select_index(1).run()   # one player on that team
    at.selectbox[4].select_index(1).run()   # game 1
    assert not at.exception
    assert len(at.get("plotly_chart")) == 3
