# Project 1 — Match Momentum Tracker

A Streamlit app that analyses doubles pickleball matches rally by rally: where
winners and unforced errors land, what kind of errors each player makes, and how
momentum swings across serving rotations.

- **Tab 1 – Upload & Overview:** upload a CSV (or use the bundled sample) and see the
  matches, tournaments and players it covers.
- **Tab 2 – Match Analysis:** pick a match, team, player and game; see KPIs, a court
  map of final shots, a stacked bar of unforced errors (net / wide / long), and a
  momentum timeline shaded by serving rotation.

## Run it

```bash
cd "Project 1"
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Test it

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
app.py              entry point: page setup and the two tabs
data_loader.py      CSV schema, validation, rotation derivation
metrics.py          calculations (pure pandas)
charts.py           Plotly figures
ui/overview_tab.py  Tab 1
ui/analysis_tab.py  Tab 2
data/               sample_matches.csv (6 matches, 3 tournaments, 8 players)
tests/              pytest suite, including an AppTest smoke test of the app
```

## CSV format

One row per rally, describing only its **final shot**.

| Column | Values |
|---|---|
| `tournament`, `match_id` | text |
| `date` | `YYYY-MM-DD` |
| `sport` | `pickleball` (v1) |
| `team_a`, `team_b` | `"Name1 / Name2"` |
| `game` | integer ≥ 1 |
| `point_number` | 1, 2, 3… across the whole match, no gaps |
| `serving_team` | `A` / `B` |
| `server_number` | `1` / `2` |
| `final_shot_player` | a player from `final_shot_team` |
| `final_shot_team` | `A` / `B` |
| `final_shot_type` | serve, return, drive, drop, dink, volley, lob, overhead |
| `court_x`, `court_y` | feet from the net centre; court is ±10 wide (x) and ±22 long (y); Team A plays the −y half |
| `outcome` | winner, unforced_error, forced_error |
| `error_type` | net, wide, long — only when `outcome` is unforced_error, otherwise blank |
| `point_winner` | `A` / `B` |

Validation rules: a `winner` is won by the hitting team and any error by the other
team; match-level columns (tournament, date, sport, teams) are constant within a
match; `point_number` is unique per match.

**Derived by the app:** `rotation_id` (a new rotation at every side-out) and the
momentum line (running total of +1 per rally won by A, −1 per rally won by B).
