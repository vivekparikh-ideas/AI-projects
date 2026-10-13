"""Doubles Racket Sports — Match Momentum Tracker.

Run with:  streamlit run app.py
"""

from pathlib import Path

import streamlit as st

from data_loader import load_csv
from ui import analysis_tab, overview_tab

SAMPLE_CSV = Path(__file__).parent / "data" / "sample_matches.csv"


@st.cache_data
def load_sample():
    return load_csv(SAMPLE_CSV)


def main() -> None:
    st.set_page_config(page_title="Match Momentum Tracker", page_icon="🏓", layout="wide")
    st.title("Match Momentum Tracker")
    st.caption("Doubles racket sports · pickleball (v1)")

    tab_overview, tab_analysis = st.tabs(["📁 Upload & Overview", "📊 Match Analysis"])

    # Tabs render top to bottom in one script run, so whatever Tab 1 loads
    # (an upload, or the bundled sample) is what Tab 2 analyses.
    with tab_overview:
        df = overview_tab.render(load_sample)
    with tab_analysis:
        analysis_tab.render(df)


if __name__ == "__main__":
    main()
